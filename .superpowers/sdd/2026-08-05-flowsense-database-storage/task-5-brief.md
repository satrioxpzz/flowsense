# Task 5: Database schema update

**Files:**
- Modify: `flowsense/database/models.py`
- Modify: `flowsense/api_server/schemas.py`

- [ ] **Step 1: Add density field to Detection**

In `flowsense/database/models.py`, `class Detection`:
```python
    density = Column(JSON)
```

In `flowsense/api_server/schemas.py`, `class DetectionBase`:
```python
    density: Optional[Dict[str, Any]] = None
```

- [ ] **Step 2: Commit**

```bash
git add flowsense/database/models.py flowsense/api_server/schemas.py
git commit -m "feat: add density field to Detection schema"
```
