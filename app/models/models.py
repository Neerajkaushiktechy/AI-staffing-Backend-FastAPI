from sqlalchemy import Column, Integer, String, Float, Text, ForeignKey, Numeric, Time, Date, TIMESTAMP
from app.database import Base

class Admin(Base):
    __tablename__ = "admin"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False)
    password = Column(String(255), nullable=False)

class Facility(Base):
    __tablename__ = "facilities"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(Text, nullable=False)
    address = Column(Text, nullable=False)
    city_state_zip = Column(Text, nullable=False)
    overtime_multiplier = Column(Numeric)
    lat = Column(Float)
    lng = Column(Float)

class Coordinator(Base):
    __tablename__ = "coordinator"
    id = Column(Integer, primary_key=True, index=True)
    facility_id = Column(Integer, ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False)
    coordinator_first_name = Column(Text, nullable=False)
    coordinator_last_name = Column(Text, nullable=False)
    coordinator_phone = Column(Text, unique=True, nullable=False)
    coordinator_email = Column(Text, unique=True, nullable=False)

class CoordinatorChatData(Base):
    __tablename__ = "coordinator_chat_data"
    id = Column(Integer, primary_key=True, index=True)
    sender = Column(String(100), ForeignKey("coordinator.coordinator_phone", ondelete="CASCADE"), nullable=False)
    message = Column(Text)
    message_type = Column(Text, nullable=False)
    created_at = Column(TIMESTAMP(timezone=False), server_default=func.now())

class Nurse(Base):
    __tablename__ = "nurses"
    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String(255), nullable=False)
    last_name = Column(String(255), nullable=False)
    location = Column(String(100), nullable=False)
    nurse_type = Column(String(255), nullable=False)
    shift = Column(String(255), nullable=False)
    mobile_number = Column(String(100), unique=True, nullable=False)
    schedule_name = Column(String(255), nullable=False)
    rate = Column(Numeric, nullable=False)
    shift_dif = Column(Numeric, nullable=False)
    ot_rate = Column(Numeric, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    talent_id = Column(String(255), unique=True, nullable=False)
    lat = Column(Float)
    lng = Column(Float)

class NurseChatData(Base):
    __tablename__ = "nurse_chat_data"
    id = Column(Integer, primary_key=True, index=True)
    mobile_number = Column(String(100), ForeignKey("nurses.mobile_number", ondelete="CASCADE"), nullable=False)
    message = Column(Text)
    message_type = Column(Text, nullable=False)
    timestamp = Column(TIMESTAMP(timezone=False), server_default=func.now())

class NurseType(Base):
    __tablename__ = "nurse_type"
    id = Column(Integer, primary_key=True, index=True)
    nurse_type = Column(String(255), unique=True, nullable=False)

class RepliedMessages(Base):
    __tablename__ = "replied_messages"
    id = Column(Integer, primary_key=True, index=True)
    text = Column(Text)
    sender = Column(String(100))
    timestamp = Column(TIMESTAMP(timezone=False), server_default=func.now())
    rowid = Column(Integer)
    guid = Column(String)

class Shift(Base):
    __tablename__ = "shifts"
    id = Column(Integer, primary_key=True, index=True)
    facility_id = Column(Integer, ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False)
    role = Column(Text, nullable=False)
    rate = Column(Numeric, nullable=False)
    hours = Column(Numeric, nullable=False)
    am_time_start = Column(Time(timezone=False))
    am_time_end = Column(Time(timezone=False))
    pm_time_start = Column(Time(timezone=False))
    pm_time_end = Column(Time(timezone=False))
    noc_time_start = Column(Time(timezone=False))
    noc_time_end = Column(Time(timezone=False))
    am_meal_start = Column(Time(timezone=False))
    am_meal_end = Column(Time(timezone=False))
    pm_meal_start = Column(Time(timezone=False))
    pm_meal_end = Column(Time(timezone=False))
    noc_meal_start = Column(Time(timezone=False))
    noc_meal_end = Column(Time(timezone=False))

class ShiftTracker(Base):
    __tablename__ = "shift_tracker"
    id = Column(Integer, primary_key=True, index=True)
    facility_id = Column(Integer, ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False)
    nurse_type = Column(String(255), nullable=False)
    shift = Column(String(525), nullable=False)
    nurse_id = Column(Integer)
    status = Column(String(255), nullable=False)
    date = Column(Date, nullable=False)
    booked_by = Column(String(255))
    additional_instructions = Column(Text)
    coordinator_id = Column(Integer, ForeignKey("coordinator.id", ondelete="CASCADE"))

