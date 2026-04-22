from sqlalchemy import Column, String, Boolean, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)          # UUID
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    jwt_token = Column(Text, nullable=False)
    attended = Column(Boolean, default=False)
    attended_at = Column(DateTime, nullable=True)
    voted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Vote(Base):
    __tablename__ = "votes"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    project_name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    team = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
