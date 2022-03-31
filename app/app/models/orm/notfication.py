from datetime import datetime

from sqlalchemy import Column, Integer, ForeignKey, String, JSON, Boolean, DateTime
from sqlalchemy.orm import relationship

from app.models.orm import Base


class Notification(Base):
    id = Column(Integer, autoincrement=True, primary_key=True)
    created = Column(DateTime, default=datetime.now)
    actor_id = Column(Integer, ForeignKey("registeredactor.id"), nullable=True)
    actor = relationship("registeredactor")
    type = Column(String, nullable=False)
    # text = Column(String, nullable=False)
    data = Column(JSON, nullable=False)
    received = Column(Boolean, nullable=False)
