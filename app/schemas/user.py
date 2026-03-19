"""
用户相关 Pydantic Schema
"""

from uuid import UUID

from pydantic import EmailStr, Field

from app.schemas.base import BaseSchema, IDSchema, TimestampSchema


class UserBase(BaseSchema):
    """用户基础信息"""

    email: EmailStr = Field(..., description="邮箱（登录名）")
    username: str | None = Field(None, max_length=100, description="展示名")


class UserCreate(BaseSchema):
    """用户注册请求"""

    email: EmailStr = Field(..., description="邮箱")
    password: str = Field(..., min_length=8, max_length=128, description="密码")
    username: str | None = Field(None, max_length=100, description="展示名")
    invite_code: str | None = Field(None, max_length=64, description="邀请码")


class UserUpdate(BaseSchema):
    """用户更新请求（自助修改）"""

    username: str | None = Field(None, max_length=100, description="展示名")
    avatar_url: str | None = Field(None, description="头像 URL（兼容字段）")
    avatar_object_key: str | None = Field(
        None, max_length=512, description="头像对象存储 key"
    )
    avatar_storage_type: str | None = Field(
        None, max_length=20, description="头像存储类型: public/private"
    )


class EmailBindingSendCodeRequest(BaseSchema):
    email: EmailStr = Field(..., description="要绑定的邮箱")


class EmailBindingConfirmRequest(BaseSchema):
    email: EmailStr = Field(..., description="要绑定的邮箱")
    code: str = Field(..., min_length=6, max_length=6, description="邮箱验证码")


class UserRead(IDSchema, TimestampSchema):
    """用户读取响应（排除敏感字段）"""

    email: str = Field(..., description="邮箱")
    username: str | None = Field(None, description="展示名")
    avatar_url: str | None = Field(None, description="头像 URL")
    is_active: bool = Field(..., description="是否启用")
    is_superuser: bool = Field(..., description="是否超级管理员")


class RoleRead(IDSchema):
    """角色读取响应"""

    name: str = Field(..., description="角色名称")
    description: str | None = Field(None, description="角色描述")


class PermissionRead(IDSchema):
    """权限读取响应"""

    code: str = Field(..., description="权限代码")
    description: str | None = Field(None, description="权限描述")


class UserWithRoles(UserRead):
    """用户信息（含角色）"""

    roles: list[RoleRead] = Field(default_factory=list, description="用户角色列表")


class UserWithPermissions(UserRead):
    """用户信息（含权限标记）"""

    permission_flags: dict[str, int] = Field(
        default_factory=dict, description="权限标记 {can_xxx: 0/1}"
    )


class OAuthBindingState(BaseSchema):
    is_bound: bool = Field(..., description="是否已绑定")
    display_name: str | None = Field(None, description="外部身份展示名")
    bound_at: str | None = Field(None, description="绑定时间")


class EmailBindingAlias(BaseSchema):
    email: str = Field(..., description="可用于邮箱验证码登录的别名邮箱")
    bound_at: str | None = Field(None, description="绑定时间")


class EmailBindingState(BaseSchema):
    primary_email: str = Field(..., description="主邮箱")
    aliases: list[EmailBindingAlias] = Field(
        default_factory=list, description="已绑定的额外邮箱登录别名"
    )


class UserBindingsRead(BaseSchema):
    oauth: dict[str, OAuthBindingState] = Field(
        default_factory=dict, description="OAuth 绑定状态"
    )
    email: EmailBindingState = Field(..., description="邮箱登录绑定状态")


class OAuthBindingConfirmResponse(BaseSchema):
    provider: str = Field(..., description="绑定的 provider")
    is_bound: bool = Field(..., description="是否已绑定")
    display_name: str | None = Field(None, description="展示名")


class UserAdminUpdate(BaseSchema):
    """管理员更新用户请求"""

    is_active: bool | None = Field(None, description="是否启用")
    is_superuser: bool | None = Field(None, description="是否超级管理员")
    username: str | None = Field(None, max_length=100, description="展示名")
    avatar_url: str | None = Field(None, description="头像 URL（兼容字段）")
    avatar_object_key: str | None = Field(
        None, max_length=512, description="头像对象存储 key"
    )
    avatar_storage_type: str | None = Field(
        None, max_length=20, description="头像存储类型: public/private"
    )


class UserListResponse(BaseSchema):
    """用户列表响应"""

    items: list[UserRead] = Field(..., description="用户列表")
    total: int = Field(..., description="总数")
    skip: int = Field(..., description="跳过数量")
    limit: int = Field(..., description="每页数量")


class RoleAssignment(BaseSchema):
    """角色分配请求"""

    role_ids: list[UUID] = Field(..., description="角色 ID 列表")
    action: str = Field(
        "add", pattern="^(add|remove)$", description="操作: add 或 remove"
    )


class BanRequest(BaseSchema):
    """封禁用户请求"""

    reason: str = Field(..., min_length=1, max_length=500, description="封禁原因")
    duration_hours: int | None = Field(
        None, ge=1, description="封禁时长（小时），不填为永久"
    )
