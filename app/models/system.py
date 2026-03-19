"""系统基础数据模型"""
from sqlalchemy import (
    Column, BigInteger, Integer, String, SmallInteger, DateTime, ForeignKey
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class SysRole(Base):
    """系统角色表"""
    __tablename__ = "sys_role"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(32), unique=True, nullable=False,
                  comment="SUPER_ADMIN/ADMIN/OPERATOR/COLLECTOR")
    name = Column(String(64), nullable=False, comment="角色名称")
    description = Column(String(256), comment="角色描述")
    status = Column(SmallInteger, nullable=False, default=1)
    sort_order = Column(SmallInteger, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    users = relationship(
        "SysUserRole",
        back_populates="role",
        cascade="all, delete-orphan",
    )


class SysUser(Base):
    """系统用户表"""
    __tablename__ = "sys_user"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, comment="用户名（登录名）")
    real_name = Column(String(64), nullable=False, comment="真实姓名")
    password_hash = Column(String(256), nullable=False, comment="密码哈希")
    phone = Column(String(32), comment="手机号")
    email = Column(String(128), comment="邮箱")
    department = Column(String(64), comment="部门")
    avatar = Column(String(256), comment="头像URL")
    # 微信小程序绑定
    wx_open_id = Column(String(64), comment="微信OpenID")
    wx_bound = Column(SmallInteger, default=0, comment="0=未绑定,1=已绑定")
    # 状态
    status = Column(SmallInteger, nullable=False, default=1, comment="1=启用,0=停用")
    last_login_at = Column(DateTime, comment="最后登录时间")
    created_by = Column(BigInteger, comment="创建人ID")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    roles = relationship(
        "SysUserRole",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class SysUserRole(Base):
    """用户角色关联表"""
    __tablename__ = "sys_user_role"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        BigInteger,
        ForeignKey("sys_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    role_id = Column(
        BigInteger,
        ForeignKey("sys_role.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("SysUser", back_populates="roles")
    role = relationship("SysRole", back_populates="users")
