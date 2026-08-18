from sqlalchemy import Column, String, Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from api.v1.models.base_class import BaseModel


class Organization(BaseModel):
    """
    Fund issuer / asset manager entity.

    Fund managers (role=fund_manager) operate under an organization that
    originates and manages investment products.
    """

    __tablename__ = "organizations"

    name = Column(String(255), nullable=False)
    contact_email = Column(String(255), nullable=False, index=True)
    region = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    website = Column(String(255), nullable=True)
    verified = Column(Boolean, default=False, nullable=False)

    created_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    creator = relationship("User", back_populates="organizations")
