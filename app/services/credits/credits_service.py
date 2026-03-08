from __future__ import annotations

import csv
import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import StringIO

from typing import Literal

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache
from app.core.cache_keys import CacheKeys
from app.models.billing import (
    AlipayRechargeOrder,
    AlipayRechargeOrderStatus,
    BillingTransaction,
    TransactionStatus,
    TransactionType,
)
from app.repositories.billing_repository import BillingRepository
from app.repositories.quota_repository import QuotaRepository
from app.schemas.credits import (
    CreditsBalanceResponse,
    CreditsConsumptionPoint,
    CreditsConsumptionResponse,
    CreditsModelUsageItem,
    CreditsModelUsageResponse,
    CreditsRechargeOrderItem,
    CreditsRechargeOrderListResponse,
    CreditsRechargeResponse,
    CreditsTransactionItem,
    CreditsTransactionListResponse,
)
from app.utils.time_utils import Datetime


class CreditsService:
    """积分/计费数据聚合服务。"""

    FAILURE_REASON_MAP = {
        "ACQ.TRADE_NOT_EXIST": "Payment order was closed or never completed.",
        "ACQ.SYSTEM_ERROR": "Payment provider temporarily failed to process the recharge.",
        "TRADE_CLOSED": "The trade was closed before payment completed.",
        "WAIT_BUYER_PAY": "The recharge is still waiting for payment.",
    }

    def __init__(self, session: AsyncSession):
        self.session = session
        self.quota_repo = QuotaRepository(session)
        self.billing_repo = BillingRepository(session)
        self._dialect = getattr(getattr(session, "bind", None), "dialect", None)

    @staticmethod
    def _normalize_tenant_id(tenant_id: str | uuid.UUID) -> tuple[str, uuid.UUID]:
        if isinstance(tenant_id, uuid.UUID):
            return str(tenant_id), tenant_id
        return tenant_id, uuid.UUID(tenant_id)

    @classmethod
    def _resolve_failure_reason(cls, order: AlipayRechargeOrder) -> str | None:
        if order.status != AlipayRechargeOrderStatus.FAILED:
            return None
        if order.error_detail:
            return order.error_detail
        if order.error_code and order.error_code in cls.FAILURE_REASON_MAP:
            return cls.FAILURE_REASON_MAP[order.error_code]
        if order.trade_status and order.trade_status in cls.FAILURE_REASON_MAP:
            return cls.FAILURE_REASON_MAP[order.trade_status]
        return order.error_code or order.trade_status or "Recharge failed."

    def _build_recharge_orders_stmt(
        self,
        tenant_uuid: uuid.UUID,
        status_filter: AlipayRechargeOrderStatus | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        query: str | None = None,
        sort_by: Literal["time", "amount"] = "time",
        sort_direction: Literal["asc", "desc"] = "desc",
    ):
        stmt = select(AlipayRechargeOrder).where(AlipayRechargeOrder.tenant_id == tenant_uuid)
        if status_filter is not None:
            stmt = stmt.where(AlipayRechargeOrder.status == status_filter)
        if start_date is not None:
            stmt = stmt.where(
                AlipayRechargeOrder.created_at
                >= datetime(start_date.year, start_date.month, start_date.day, tzinfo=UTC)
            )
        if end_date is not None:
            stmt = stmt.where(
                AlipayRechargeOrder.created_at
                < datetime(end_date.year, end_date.month, end_date.day, tzinfo=UTC)
                + timedelta(days=1)
            )
        if query:
            normalized_query = f"%{query.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(AlipayRechargeOrder.out_trade_no).like(normalized_query),
                    func.lower(func.coalesce(AlipayRechargeOrder.trade_no, "")).like(
                        normalized_query
                    ),
                )
            )

        sort_column = (
            AlipayRechargeOrder.amount if sort_by == "amount" else AlipayRechargeOrder.created_at
        )
        sort_fn = asc if sort_direction == "asc" else desc
        return stmt.order_by(sort_fn(sort_column), desc(AlipayRechargeOrder.created_at))

    def _serialize_recharge_order(self, order: AlipayRechargeOrder) -> CreditsRechargeOrderItem:
        return CreditsRechargeOrderItem(
            id=str(order.id),
            out_trade_no=order.out_trade_no,
            trade_no=order.trade_no,
            status=order.status.value,
            trade_status=order.trade_status,
            amount=float(order.amount),
            currency=order.currency,
            expected_credited_amount=float(order.expected_credited_amount),
            credited_amount=(
                float(order.expected_credited_amount)
                if order.status == AlipayRechargeOrderStatus.SUCCESS
                else 0.0
            ),
            channel="alipay",
            error_code=order.error_code,
            error_detail=order.error_detail,
            failure_reason=self._resolve_failure_reason(order),
            created_at=order.created_at,
            settled_at=order.settled_at,
        )

    async def get_balance(self, tenant_id: str | None) -> CreditsBalanceResponse:
        if not tenant_id:
            return CreditsBalanceResponse(balance=0, monthly_spent=0, used_percent=0)

        tenant_id_str, tenant_uuid = self._normalize_tenant_id(tenant_id)
        cache_key = CacheKeys.credits_balance(tenant_id_str)
        cached = await cache.get(cache_key)
        if cached:
            return cached

        quota = await self.quota_repo.get_or_create(tenant_uuid)
        balance = float(quota.balance)

        now = Datetime.now()
        start_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_spent = await self._sum_amount(start_month, now, tenant_uuid)

        denominator = monthly_spent + balance
        used_percent = (
            round((monthly_spent / denominator) * 100, 2) if denominator > 0 else 0.0
        )

        resp = CreditsBalanceResponse(
            balance=balance,
            monthly_spent=monthly_spent,
            used_percent=used_percent,
        )
        await cache.set(cache_key, resp, ttl=30)
        return resp

    async def get_consumption(
        self, tenant_id: str | None, days: int
    ) -> CreditsConsumptionResponse:
        days = max(1, min(days, 90))
        if not tenant_id:
            return self._empty_consumption(days)

        tenant_id_str, tenant_uuid = self._normalize_tenant_id(tenant_id)
        cache_key = CacheKeys.credits_consumption(tenant_id_str, days)
        cached = await cache.get(cache_key)
        if cached:
            return cached

        now = Datetime.now()
        start_date = (now - timedelta(days=days - 1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        bucket_expr = self._date_bucket_expr()
        model_expr = func.coalesce(BillingTransaction.model, "unknown")
        total_tokens = (
            BillingTransaction.input_tokens + BillingTransaction.output_tokens
        )

        stmt = (
            select(
                bucket_expr.label("bucket"),
                model_expr.label("model"),
                func.sum(total_tokens).label("tokens"),
            )
            .where(
                BillingTransaction.created_at >= start_date,
                BillingTransaction.created_at <= now,
                BillingTransaction.tenant_id == tenant_uuid,
                BillingTransaction.status == TransactionStatus.COMMITTED,
                BillingTransaction.type == TransactionType.DEDUCT,
            )
            .group_by(bucket_expr, model_expr)
        )

        rows = (await self.session.execute(stmt)).all()
        models = sorted({row.model for row in rows})
        tokens_map: dict[tuple[str, str], int] = {
            (row.bucket, row.model): int(row.tokens or 0) for row in rows
        }

        timeline = []
        for day in self._iter_days(start_date, days):
            day_key = day.strftime("%Y-%m-%d")
            tokens_by_model = {
                model: tokens_map.get((day_key, model), 0) for model in models
            }
            timeline.append(
                CreditsConsumptionPoint(date=day_key, tokens_by_model=tokens_by_model)
            )

        resp = CreditsConsumptionResponse(
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=now.strftime("%Y-%m-%d"),
            days=days,
            models=models,
            timeline=timeline,
        )
        await cache.set(cache_key, resp, ttl=60)
        return resp

    async def get_model_usage(
        self, tenant_id: str | None, days: int
    ) -> CreditsModelUsageResponse:
        days = max(1, min(days, 90))
        if not tenant_id:
            return CreditsModelUsageResponse(total_tokens=0, models=[])

        tenant_id_str, tenant_uuid = self._normalize_tenant_id(tenant_id)
        cache_key = CacheKeys.credits_model_usage(tenant_id_str, days)
        cached = await cache.get(cache_key)
        if cached:
            return cached

        now = Datetime.now()
        start_date = (now - timedelta(days=days - 1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        model_expr = func.coalesce(BillingTransaction.model, "unknown")
        total_tokens = (
            BillingTransaction.input_tokens + BillingTransaction.output_tokens
        )

        stmt = (
            select(
                model_expr.label("model"),
                func.sum(total_tokens).label("tokens"),
            )
            .where(
                BillingTransaction.created_at >= start_date,
                BillingTransaction.created_at <= now,
                BillingTransaction.tenant_id == tenant_uuid,
                BillingTransaction.status == TransactionStatus.COMMITTED,
                BillingTransaction.type == TransactionType.DEDUCT,
            )
            .group_by(model_expr)
            .order_by(func.sum(total_tokens).desc())
        )
        rows = (await self.session.execute(stmt)).all()
        total = int(sum((row.tokens or 0) for row in rows))
        items: list[CreditsModelUsageItem] = []
        for row in rows:
            tokens = int(row.tokens or 0)
            percentage = round((tokens / total) * 100, 2) if total else 0.0
            items.append(
                CreditsModelUsageItem(
                    model=row.model, tokens=tokens, percentage=percentage
                )
            )

        resp = CreditsModelUsageResponse(total_tokens=total, models=items)
        await cache.set(cache_key, resp, ttl=120)
        return resp

    async def list_transactions(
        self,
        tenant_id: str | None,
        limit: int = 20,
        offset: int = 0,
    ) -> CreditsTransactionListResponse:
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        if not tenant_id:
            return CreditsTransactionListResponse(items=[], next_offset=None)

        transactions = await self.billing_repo.list_transactions(
            tenant_id=tenant_id,
            limit=limit + 1,
            offset=offset,
            status=TransactionStatus.COMMITTED,
            type_filter=TransactionType.DEDUCT,
        )

        has_more = len(transactions) > limit
        if has_more:
            transactions = transactions[:limit]

        items = [
            CreditsTransactionItem(
                id=str(tx.id),
                trace_id=tx.trace_id,
                model=tx.model,
                status="success",
                amount=float(tx.amount),
                input_tokens=int(tx.input_tokens or 0),
                output_tokens=int(tx.output_tokens or 0),
                total_tokens=int((tx.input_tokens or 0) + (tx.output_tokens or 0)),
                created_at=tx.created_at,
            )
            for tx in transactions
        ]

        next_offset = offset + limit if has_more else None
        return CreditsTransactionListResponse(items=items, next_offset=next_offset)

    async def recharge(
        self,
        tenant_id: str | None,
        amount: float,
        credit_per_unit: float,
        currency: str,
    ) -> CreditsRechargeResponse:
        trace_id = f"credits-recharge-{uuid.uuid4().hex[:24]}"
        return await self.recharge_with_trace_id(
            tenant_id=tenant_id,
            amount=amount,
            credit_per_unit=credit_per_unit,
            currency=currency,
            trace_id=trace_id,
        )

    async def list_recharge_orders(
        self,
        tenant_id: str | None,
        limit: int = 20,
        offset: int = 0,
        status_filter: AlipayRechargeOrderStatus | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        query: str | None = None,
        sort_by: Literal["time", "amount"] = "time",
        sort_direction: Literal["asc", "desc"] = "desc",
    ) -> CreditsRechargeOrderListResponse:
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        if not tenant_id:
            return CreditsRechargeOrderListResponse(items=[], next_offset=None)

        _, tenant_uuid = self._normalize_tenant_id(tenant_id)
        stmt = self._build_recharge_orders_stmt(
            tenant_uuid,
            status_filter,
            start_date,
            end_date,
            query,
            sort_by,
            sort_direction,
        ).limit(limit + 1).offset(offset)

        orders = list((await self.session.execute(stmt)).scalars().all())
        has_more = len(orders) > limit
        if has_more:
            orders = orders[:limit]

        items = [self._serialize_recharge_order(order) for order in orders]

        next_offset = offset + limit if has_more else None
        return CreditsRechargeOrderListResponse(items=items, next_offset=next_offset)

    async def export_recharge_orders_csv(
        self,
        tenant_id: str | None,
        status_filter: AlipayRechargeOrderStatus | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        query: str | None = None,
        sort_by: Literal["time", "amount"] = "time",
        sort_direction: Literal["asc", "desc"] = "desc",
    ) -> str:
        if not tenant_id:
            return ""

        _, tenant_uuid = self._normalize_tenant_id(tenant_id)
        stmt = self._build_recharge_orders_stmt(
            tenant_uuid,
            status_filter,
            start_date,
            end_date,
            query,
            sort_by,
            sort_direction,
        )
        orders = list((await self.session.execute(stmt)).scalars().all())

        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "outTradeNo",
                "status",
                "tradeStatus",
                "amount",
                "creditedAmount",
                "currency",
                "tradeNo",
                "channel",
                "failureReason",
                "createdAt",
                "settledAt",
            ]
        )

        for order in orders:
            item = self._serialize_recharge_order(order)
            writer.writerow(
                [
                    item.out_trade_no,
                    item.status,
                    item.trade_status or "",
                    item.amount,
                    item.credited_amount,
                    item.currency,
                    item.trade_no or "",
                    item.channel,
                    item.failure_reason or "",
                    item.created_at.isoformat(),
                    item.settled_at.isoformat() if item.settled_at else "",
                ]
            )

        return buffer.getvalue()

    async def recharge_with_trace_id(
        self,
        tenant_id: str | None,
        amount: float | Decimal,
        credit_per_unit: float,
        currency: str,
        trace_id: str,
        description: str | None = None,
    ) -> CreditsRechargeResponse:
        if not tenant_id:
            raise ValueError("无效的用户信息")
        amount_decimal = Decimal(str(amount))
        if amount_decimal <= 0:
            raise ValueError("充值金额必须大于 0")
        if credit_per_unit <= 0:
            raise ValueError("充值比例必须大于 0")
        if not trace_id:
            raise ValueError("充值流水标识不能为空")

        tenant_id_str, tenant_uuid = self._normalize_tenant_id(tenant_id)
        credited_amount = (
            amount_decimal * Decimal(str(credit_per_unit))
        ).quantize(Decimal("0.000001"))

        if credited_amount <= Decimal("0"):
            raise ValueError("充值积分必须大于 0")

        tx = await self.billing_repo.recharge(
            tenant_id=tenant_uuid,
            amount=credited_amount,
            trace_id=trace_id,
            description=description
            or (
                f"Credits recharge amount={amount_decimal} {currency}, "
                f"ratio={credit_per_unit}"
            ),
        )
        await cache.delete(CacheKeys.credits_balance(tenant_id_str))

        return CreditsRechargeResponse(
            amount=float(amount_decimal),
            credited_amount=float(tx.amount),
            currency=currency,
            balance=float(tx.balance_after),
            trace_id=tx.trace_id,
        )

    def _date_bucket_expr(self):
        if self._dialect and self._dialect.name == "postgresql":
            return func.to_char(BillingTransaction.created_at, "YYYY-MM-DD")
        return func.strftime("%Y-%m-%d", BillingTransaction.created_at)

    @staticmethod
    def _iter_days(start_date, days: int) -> Iterable:
        cursor = start_date
        for _ in range(days):
            yield cursor
            cursor += timedelta(days=1)

    @staticmethod
    def _empty_consumption(days: int) -> CreditsConsumptionResponse:
        now = Datetime.now()
        start_date = (now - timedelta(days=days - 1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        timeline = [
            CreditsConsumptionPoint(
                date=(start_date + timedelta(days=i)).strftime("%Y-%m-%d"),
                tokens_by_model={},
            )
            for i in range(days)
        ]
        return CreditsConsumptionResponse(
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=now.strftime("%Y-%m-%d"),
            days=days,
            models=[],
            timeline=timeline,
        )

    async def _sum_amount(self, start, end, tenant_id: uuid.UUID) -> float:
        stmt = select(func.sum(BillingTransaction.amount)).where(
            BillingTransaction.created_at >= start,
            BillingTransaction.created_at <= end,
            BillingTransaction.tenant_id == tenant_id,
            BillingTransaction.status == TransactionStatus.COMMITTED,
            BillingTransaction.type == TransactionType.DEDUCT,
        )
        result = await self.session.execute(stmt)
        value = result.scalar() or Decimal("0")
        return float(value)
