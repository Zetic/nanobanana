# Persistence System Documentation

## Overview

The Nano Banana Discord Bot now features a comprehensive persistence system that enables **true persistence** across bot restarts. Unlike the previous implementation that showed "Interaction Expired" messages after restarts, the new system saves all interaction data and restores full functionality.

## Key Features

- ✅ **No more "Interaction Expired" messages** after bot restarts
- ✅ **Input image persistence** - all uploaded images are saved with unique IDs
- ✅ **Output image persistence** - generated images are saved with interaction context
- ✅ **Complete interaction state** - prompts, settings, and view state preserved
- ✅ **Automatic cleanup** - old interaction data is cleaned up periodically
- ✅ **Graceful degradation** - handles missing files and corrupted data

## Architecture

### Components

1. **PersistenceManager** (`persistence.py`)
   - Manages file storage and JSON state persistence
   - Handles input/output image storage with ID-based naming
   - Provides cleanup and maintenance functions

2. **Enhanced Data Models**
   - `OutputItem` - Extended with `interaction_id` and persistence conversion methods
   - `PersistedInteractionState` - Complete serializable interaction state
   - `PersistedOutputItem` - File-based representation of generated outputs

3. **Updated View Classes**
   - `StyleOptionsView` - Saves/restores state automatically, attempts recovery on interactions
   - `ProcessRequestView` - Full persistence support with input image saving

### File Structure

```
bot_data/
├── states/                          # JSON interaction state files
│   ├── {interaction-id-1}.json
│   └── {interaction-id-2}.json
├── input_images/                    # User-uploaded images
│   ├── input_{interaction-id}_0_{timestamp}.png
│   └── input_{interaction-id}_1_{timestamp}.png
└── output_images/                   # Generated images with ID tracking
    ├── output_{interaction-id}_generated_{timestamp}.png
    └── output_{interaction-id}_styled_{timestamp}.png
```

## How It Works

### 1. Interaction Creation
When a user mentions the bot:
1. A unique `interaction_id` is generated using UUID4
2. All input images are saved to `bot_data/input_images/` with the interaction ID
3. A `ProcessRequestView` is created with the interaction ID
4. Initial state is saved to `bot_data/states/{interaction-id}.json`

### 2. Image Generation
When images are generated:
1. Output images are saved to `generated_images/` (existing behavior)
2. Images are also copied to `bot_data/output_images/` with interaction ID naming
3. `OutputItem` objects include the interaction ID
4. View state is updated and re-saved to persistence

### 3. View Persistence
Both `StyleOptionsView` and `ProcessRequestView`:
- Save their complete state after creation and any state changes
- Include interaction ID in embed footers for debugging
- Attempt state restoration when accessed after restart

### 4. Bot Restart Recovery
When the bot restarts:
1. Empty persistent views are registered with `bot.add_view()`
2. When a user clicks buttons on old messages:
   - Views attempt to extract interaction ID from embed footer
   - State is loaded from `bot_data/states/{interaction-id}.json`
   - Images are loaded from `bot_data/input_images/` and `bot_data/output_images/`
   - View continues functioning with restored data

## Usage Examples

### Normal Operation
```python
# User mentions bot with image
# -> interaction_id: "123e4567-e89b-12d3-a456-426614174000"
# -> Input image saved: bot_data/input_images/input_123e4567-e89b-12d3-a456-426614174000_0_20240831_120000.png
# -> State saved: bot_data/states/123e4567-e89b-12d3-a456-426614174000.json

# User clicks process button
# -> Generated image saved: generated_images/generated_20240831_120030.png
# -> Copy saved: bot_data/output_images/output_123e4567-e89b-12d3-a456-426614174000_generated_20240831_120030.png
# -> State updated with new output

# User navigates between outputs
# -> State updated with current_index
```

### After Bot Restart
```python
# User clicks navigation button on old message
# -> View extracts interaction_id from embed footer
# -> StyleOptionsView.from_interaction_id("123e4567-e89b-12d3-a456-426614174000")
# -> State loaded from JSON
# -> Images loaded from persistence directories
# -> View continues functioning normally
```

## Configuration

### Environment Variables
No additional environment variables required. The system uses:
- `GENERATED_IMAGES_DIR` from config (existing)
- `bot_data/` directory created automatically

### Cleanup Configuration
```python
# Clean up interactions older than 30 days (default)
persistence_manager.cleanup_old_states(max_age_days=30)

# Clean up everything (for testing)
persistence_manager.cleanup_old_states(max_age_days=0)
```

## Error Handling

The system includes comprehensive error handling:

1. **Missing Files**: If persisted images are missing, placeholder images are created
2. **Corrupted State**: Invalid JSON files are logged and ignored
3. **ID Extraction Failure**: Falls back to showing helpful error message
4. **Storage Errors**: Logged but don't prevent bot operation

## Performance Considerations

### Storage Usage
- Input images: ~1-8MB per image (user uploads)
- Output images: ~1-2MB per generation (PNG format)
- State files: ~1-5KB per interaction (JSON)
- Estimated: ~10-20MB per 100 interactions

### Cleanup Strategy
- Automatic cleanup of interactions older than 30 days
- Manual cleanup available via `cleanup_old_states()`
- Cleanup removes state files and associated images
- No impact on currently active interactions

## Testing

The persistence system includes comprehensive tests:

### Unit Tests (`test_persistence_unit.py`)
- Basic persistence manager functionality
- Interaction ID generation and uniqueness
- Input/output image saving and loading
- State serialization and deserialization
- Cross-restart persistence verification
- Error handling and edge cases

### Integration Tests (`test_persistence.py`)
- End-to-end persistence workflow
- Data consistency verification
- Performance validation

### Running Tests
```bash
cd /home/runner/work/nanobanana/nanobanana
python test_persistence_unit.py
python test_persistence.py
```

## Migration Notes

### From Previous Version
The new persistence system is **fully backward compatible**:
- Existing persistent views continue to work
- Old interactions show improved error messages
- No data migration required
- No breaking changes to existing functionality

### Upgrading
1. Update bot code with new persistence system
2. Bot creates `bot_data/` directory automatically
3. New interactions use persistence
4. Old interactions gracefully show "could not restore" message instead of generic "expired"

## Troubleshooting

### Common Issues

**"Interaction data could not be restored"**
- Cause: State file missing or corrupted
- Solution: This is normal for very old interactions; user should create new request

**High disk usage**
- Cause: Many saved interactions
- Solution: Run cleanup: `persistence_manager.cleanup_old_states(max_age_days=7)`

**Images not loading**
- Cause: Image files moved or deleted
- Solution: System creates gray placeholder; user should create new request

### Debug Information

Each embed footer shows the interaction ID for debugging:
```
Footer: "Persistent Session ID: 123e4567-e89b-12d3-a456-426614174000"
```

Check logs for persistence operations:
```
INFO - Saved interaction state: 123e4567-e89b-12d3-a456-426614174000
INFO - Loaded interaction state: 123e4567-e89b-12d3-a456-426614174000
WARNING - Interaction state not found: invalid-id
```

## Future Enhancements

Potential improvements for the persistence system:

1. **Database Backend**: Replace JSON files with SQLite or PostgreSQL
2. **Cloud Storage**: Store images in S3/GCS for multi-instance deployments
3. **Compression**: Compress stored images to reduce storage usage
4. **Metrics**: Track persistence usage and performance
5. **Backup/Restore**: Tools for backing up and restoring bot data

## Security Considerations

- Interaction IDs are UUIDs (not guessable)
- No sensitive data stored in persistence files
- File permissions should restrict access to bot process only
- Consider encryption for sensitive deployment environments