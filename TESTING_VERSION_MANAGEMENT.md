# 🧪 Version Management Testing Guide

## 📋 Pre-requisites

### 1. Run Database Migration

**Local Development:**
```bash
python migrate_add_versions.py
```

**Production (Railway/Heroku):**
```bash
# SSH into your container or use Railway CLI
railway run python migrate_add_versions.py

# Or use Flask-Migrate
flask db migrate -m "Add ModelVersion table"
flask db upgrade
```

### 2. Restart Application
```bash
# Local
python app.py

# Production
# Restart will happen automatically after push
```

## 🎯 Test Scenarios

### Test 1: Initial Upload ✅

**Steps:**
1. Go to homepage
2. Upload a new model (STL/OBJ/FBX)
3. Wait for conversion
4. Open model viewer
5. Click "📜 Version History" panel

**Expected Result:**
```
✅ Version 1 appears
   - Operation: "Initial Upload" (📤)
   - Status: "Current" badge
   - Actions: Download button only
```

**Screenshot Location:**
```
Version 1
📤 Initial Upload
📅 2025-11-02 14:30:00
💾 500 KB
📏 10×20×15 cm
💬 Initial upload
[⬇️ Download]
```

---

### Test 2: Transform Modification ✅

**Steps:**
1. Open Transform panel
2. Change scale to 2.0
3. Rotate X: 45°
4. Click "💾 Save Changes"
5. Wait for success message
6. Open Version History panel

**Expected Result:**
```
✅ Version 2 appears
   - Operation: "Transform Applied" (🔄)
   - Status: "Current" badge
   - Version 1 still visible below
   - Actions: Restore, Download, Delete
```

**Version List:**
```
Version 2 [Current]
🔄 Transform Applied
📅 2025-11-02 14:32:00
💾 520 KB
📏 20×40×30 cm (scaled 2x)
💬 Model modifications saved
[⬇️ Download]

Version 1
📤 Initial Upload
📅 2025-11-02 14:30:00
💾 500 KB
📏 10×20×15 cm
[↩️ Restore] [⬇️ Download] [🗑️]
```

---

### Test 3: Material Change ✅

**Steps:**
1. Open Material Editor panel
2. Change color to red (#ff0000)
3. Set metalness to 0.8
4. Set roughness to 0.2
5. Click "💾 Save Changes"
6. Check Version History

**Expected Result:**
```
✅ Version 3 appears
   - Operation: "Material Changed" (🎨)
   - Status: "Current" badge
   - Previous versions still visible
```

---

### Test 4: Slice Operation ✅

**Steps:**
1. Open Model Slicer panel
2. Enable slicer
3. Select X axis
4. Set position to 50%
5. Click "Apply Slice"
6. Check Version History

**Expected Result:**
```
✅ Version 4 appears
   - Operation: "Model Sliced" (✂️)
   - Status: "Current" badge
   - Comment: "Sliced model (keep positive side)"
```

---

### Test 5: Version Restore ✅

**Steps:**
1. Open Version History
2. Find Version 2 (Transform Applied)
3. Click "↩️ Restore"
4. Confirm dialog
5. Wait for page reload

**Expected Result:**
```
✅ Version 5 appears
   - Operation: "Version Restored" (↩️)
   - Status: "Current" badge
   - Comment: "Restored from version 2"
   - Model viewer shows Version 2 state
```

**Important:** Current state (Version 4) is preserved as Version 5 before restoring!

---

### Test 6: Version Download ✅

**Steps:**
1. Open Version History
2. Select any version
3. Click "⬇️ Download"

**Expected Result:**
```
✅ File downloads as "model_v{number}.glb"
✅ File can be opened in 3D viewer
✅ File matches the version state
```

---

### Test 7: Version Delete ✅

**Steps:**
1. Open Version History
2. Select old version (not current)
3. Click "🗑️" button
4. Confirm dialog

**Expected Result:**
```
✅ Version deleted
✅ Version list refreshes
✅ File removed from disk
✅ Database entry removed
```

**Note:** Cannot delete current version!

---

### Test 8: Multiple Operations ✅

**Complete Workflow:**
```
1. Upload model → Version 1 (upload)
2. Scale 2x → Version 2 (transform)
3. Change color → Version 3 (material)
4. Slice X-axis → Version 4 (slice)
5. Restore to v2 → Version 5 (restore)
6. Rotate 90° → Version 6 (transform)
7. Slice Y-axis → Version 7 (slice)
```

**Expected Result:**
```
✅ All 7 versions visible
✅ Each has correct operation type
✅ Each has correct timestamp
✅ Each has correct dimensions
✅ Version 7 is marked "Current"
```

---

## 🔍 Verification Checklist

### Backend Verification

```bash
# Check database
sqlite3 instance/app.db

# List all versions
SELECT * FROM model_version ORDER BY created_at DESC;

# Count versions per model
SELECT model_id, COUNT(*) as version_count 
FROM model_version 
GROUP BY model_id;

# Check file existence
ls -la converted/{model_id}/version_*.glb
```

### Frontend Verification

**Console Checks:**
```javascript
// Open browser console (F12)

// Check version loading
// Should see: "Loading versions..."

// Check API response
fetch('/api/versions/{model_id}')
  .then(r => r.json())
  .then(console.log);

// Should see array of versions
```

**Visual Checks:**
- ✅ Version panel opens/closes
- ✅ Versions load automatically
- ✅ Icons display correctly
- ✅ Colors match operation types
- ✅ Buttons work (Restore, Download, Delete)
- ✅ Refresh button works
- ✅ Current version has blue border
- ✅ Timestamps are correct
- ✅ File sizes are formatted

---

## 🐛 Troubleshooting

### Problem: No versions appear

**Solution:**
```bash
# Check if migration ran
python migrate_add_versions.py

# Check if table exists
sqlite3 instance/app.db "SELECT * FROM sqlite_master WHERE name='model_version';"

# Check logs
tail -f logs/app.log | grep version
```

### Problem: Version creation fails

**Check:**
1. File permissions on `converted/` folder
2. Disk space available
3. Backend logs for errors
4. Database connection

**Debug:**
```python
# In app.py, add more logging
logger.info(f"Creating version for {model_id}")
logger.info(f"Operation: {operation_type}")
logger.info(f"Details: {operation_details}")
```

### Problem: Restore doesn't work

**Check:**
1. Version file exists: `converted/{uuid}/version_{N}.glb`
2. File permissions
3. Database entry exists
4. Backend logs

**Manual restore:**
```bash
# Copy version file to current
cp converted/{uuid}/version_2.glb converted/{uuid}/model.glb
```

### Problem: UI doesn't load

**Check:**
1. Browser console for JavaScript errors
2. Network tab for API calls
3. Version panel ID in `allPanelIds` array
4. JavaScript syntax errors

**Debug:**
```javascript
// In browser console
loadVersionHistory();  // Manual trigger
console.log(versionHistory);  // Check data
```

---

## 📊 Performance Testing

### Load Test
```bash
# Create 100 versions
for i in {1..100}; do
  # Make modification
  # Save
  # Check version created
done

# Check performance
time curl http://localhost:5000/api/versions/{model_id}
```

### Storage Test
```bash
# Check disk usage
du -sh converted/{model_id}/

# Count version files
ls -1 converted/{model_id}/version_*.glb | wc -l

# Total size
du -ch converted/{model_id}/version_*.glb | tail -1
```

### Cleanup Test
```python
# Test automatic cleanup
from version_manager import cleanup_old_versions

# Keep only last 5 versions
cleanup_old_versions(model_id, keep_last_n=5)

# Verify
versions = get_version_history(model_id)
assert len(versions) <= 5
```

---

## ✅ Success Criteria

### Functional Requirements
- [x] Version created on upload
- [x] Version created on transform
- [x] Version created on material change
- [x] Version created on slice
- [x] Version created on restore
- [x] Restore preserves current state
- [x] Download works for all versions
- [x] Delete works for old versions
- [x] UI displays all versions
- [x] UI updates after operations

### Non-Functional Requirements
- [x] API response < 1 second
- [x] UI loads < 500ms
- [x] File operations < 2 seconds
- [x] Database queries optimized
- [x] No memory leaks
- [x] Mobile responsive

### User Experience
- [x] Clear visual feedback
- [x] Intuitive icons and colors
- [x] Helpful error messages
- [x] Confirmation dialogs
- [x] Loading indicators
- [x] Success notifications

---

## 📝 Test Report Template

```markdown
# Version Management Test Report

**Date:** 2025-11-02
**Tester:** [Your Name]
**Environment:** Local / Production

## Test Results

| Test Case | Status | Notes |
|-----------|--------|-------|
| Initial Upload | ✅ Pass | Version 1 created |
| Transform | ✅ Pass | Version 2 created |
| Material | ✅ Pass | Version 3 created |
| Slice | ✅ Pass | Version 4 created |
| Restore | ✅ Pass | Version 5 created |
| Download | ✅ Pass | File downloaded |
| Delete | ✅ Pass | Version removed |
| UI Display | ✅ Pass | All versions visible |

## Issues Found

1. [Issue description]
   - Severity: High/Medium/Low
   - Steps to reproduce
   - Expected vs Actual

## Performance Metrics

- API response time: 250ms
- UI load time: 150ms
- File operation time: 1.2s
- Total versions tested: 10

## Recommendations

1. [Recommendation 1]
2. [Recommendation 2]

## Sign-off

✅ All tests passed
✅ Ready for production
```

---

## 🚀 Next Steps After Testing

1. **Monitor Production**
   - Check error logs
   - Monitor disk usage
   - Track API performance

2. **User Feedback**
   - Collect user feedback
   - Identify pain points
   - Plan improvements

3. **Optimization**
   - Implement cleanup automation
   - Add compression
   - Optimize queries

4. **Documentation**
   - Update user guide
   - Create video tutorial
   - Add tooltips

---

## 📞 Support

**Issues:** https://github.com/melikhanmutlu/web_ar/issues
**Docs:** VERSION_MANAGEMENT.md
**Contact:** [Your Email]
