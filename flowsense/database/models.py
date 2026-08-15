from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean, JSON
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry
from .database import Base

class Camera(Base):
    __tablename__ = "cameras"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    url = Column(String)
    location_lat = Column(Float)
    location_lng = Column(Float)
    location = Column(Geometry('POINT'))
    status = Column(String, default="offline")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    detections = relationship("Detection", back_populates="camera")

class Detection(Base):
    __tablename__ = "detections"
    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"))
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    total_vehicles = Column(Integer, default=0)
    per_lane = Column(JSON)
    crossings = Column(JSON)
    density = Column(JSON)
    pedestrians = Column(Integer, default=0)
    vision = Column(JSON)
    speeds = Column(JSON)
    lane_avg_speeds = Column(JSON)
    anomalies = Column(JSON)
    signal_recommendations = Column(JSON)
    camera = relationship("Camera", back_populates="detections")

class Intersection(Base):
    __tablename__ = "intersections"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    location_lat = Column(Float)
    location_lng = Column(Float)
    location = Column(Geometry('POINT'))
    signal_config = Column(JSON)
    signals = relationship("TrafficSignal", back_populates="intersection")
    alerts = relationship("Alert", back_populates="intersection")

class TrafficSignal(Base):
    __tablename__ = "traffic_signals"
    id = Column(Integer, primary_key=True, index=True)
    intersection_id = Column(Integer, ForeignKey("intersections.id"))
    phase = Column(String)
    state = Column(String)
    duration = Column(Integer)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    intersection = relationship("Intersection", back_populates="signals")

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    role = Column(String, default="user")
    created_at = Column(DateTime, default=datetime.utcnow)

class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True, index=True)
    type = Column(String)
    severity = Column(String)
    message = Column(String)
    intersection_id = Column(Integer, ForeignKey("intersections.id"))
    acknowledged = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    intersection = relationship("Intersection", back_populates="alerts")
