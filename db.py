from sqlalchemy import create_engine, Column, Integer, String, Boolean, MetaData
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "sqlite:///subscriptions.db"

engine = create_engine(DATABASE_URL)
Base = declarative_base()
metadata = MetaData()

class Subscription(Base):
    __tablename__ = 'subscriptions'
    user_id = Column(Integer, primary_key=True, index=True)
    news = Column(Boolean, default=False)
    events = Column(Boolean, default=False)
    updates = Column(Boolean, default=False)

Base.metadata.create_all(bind=engine)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
