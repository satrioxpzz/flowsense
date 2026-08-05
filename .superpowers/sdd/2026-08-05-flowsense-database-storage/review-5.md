445a174 feat: add density field to Detection schema
 flowsense/api_server/schemas.py |  1 +
 flowsense/database/models.py    |  1 +
 tests/test_database_schema.py   | 51 +++++++++++++++++++++++++++++++++++++++++
 3 files changed, 53 insertions(+)
diff --git a/flowsense/api_server/schemas.py b/flowsense/api_server/schemas.py
index d4b4abf..db50b1a 100644
--- a/flowsense/api_server/schemas.py
+++ b/flowsense/api_server/schemas.py
@@ -17,20 +17,21 @@ class CameraResponse(CameraBase):
     created_at: datetime
     updated_at: datetime
     model_config = ConfigDict(from_attributes=True)
 
 class DetectionBase(BaseModel):
     camera_id: int
     timestamp: datetime
     total_vehicles: int
     per_lane: Dict[str, Any]
     crossings: Dict[str, Any]
+    density: Optional[Dict[str, Any]] = None
 
 class DetectionCreate(DetectionBase):
     pass
 
 class DetectionResponse(DetectionBase):
     id: int
     model_config = ConfigDict(from_attributes=True)
 
 class IntersectionBase(BaseModel):
     name: str
diff --git a/flowsense/database/models.py b/flowsense/database/models.py
index 1b2143b..b11f0cc 100644
--- a/flowsense/database/models.py
+++ b/flowsense/database/models.py
@@ -18,20 +18,21 @@ class Camera(Base):
     detections = relationship("Detection", back_populates="camera")
 
 class Detection(Base):
     __tablename__ = "detections"
     id = Column(Integer, primary_key=True, index=True)
     camera_id = Column(Integer, ForeignKey("cameras.id"))
     timestamp = Column(DateTime, default=datetime.utcnow, index=True)
     total_vehicles = Column(Integer, default=0)
     per_lane = Column(JSON)
     crossings = Column(JSON)
+    density = Column(JSON)
     camera = relationship("Camera", back_populates="detections")
 
 class Intersection(Base):
     __tablename__ = "intersections"
     id = Column(Integer, primary_key=True, index=True)
     name = Column(String, index=True)
     location_lat = Column(Float)
     location_lng = Column(Float)
     location = Column(Geometry('POINT'))
     signal_config = Column(JSON)
diff --git a/tests/test_database_schema.py b/tests/test_database_schema.py
new file mode 100644
index 0000000..4e44ec4
--- /dev/null
+++ b/tests/test_database_schema.py
@@ -0,0 +1,51 @@
+from datetime import datetime, timezone
+from flowsense.database.models import Detection
+from flowsense.api_server.schemas import DetectionBase, DetectionCreate, DetectionResponse
+
+
+def test_detection_model_density_column():
+    assert hasattr(Detection, "density")
+    detection = Detection(
+        camera_id=1,
+        total_vehicles=10,
+        per_lane={"lane1": 5},
+        crossings={},
+        density={"level": "HIGH", "score": 0.85},
+    )
+    assert detection.density == {"level": "HIGH", "score": 0.85}
+
+
+def test_detection_schema_density_optional():
+    now = datetime.now(timezone.utc)
+    # Test default None
+    det_base = DetectionBase(
+        camera_id=1,
+        timestamp=now,
+        total_vehicles=5,
+        per_lane={},
+        crossings={},
+    )
+    assert det_base.density is None
+
+    # Test with density dict provided
+    det_create = DetectionCreate(
+        camera_id=1,
+        timestamp=now,
+        total_vehicles=5,
+        per_lane={},
+        crossings={},
+        density={"level": "LOW", "score": 0.2},
+    )
+    assert det_create.density == {"level": "LOW", "score": 0.2}
+
+    det_resp = DetectionResponse(
+        id=42,
+        camera_id=1,
+        timestamp=now,
+        total_vehicles=5,
+        per_lane={},
+        crossings={},
+        density={"level": "MEDIUM", "score": 0.5},
+    )
+    assert det_resp.id == 42
+    assert det_resp.density == {"level": "MEDIUM", "score": 0.5}
