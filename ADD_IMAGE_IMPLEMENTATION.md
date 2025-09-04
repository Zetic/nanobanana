# Implementation Documentation (DEPRECATED)

⚠️ **NOTE: This documentation describes features that have been removed.**

As of the latest version, the bot has been simplified to return natural API responses instead of using interactive embeds and buttons. The functionality described in this file no longer exists.

The bot now:
- Returns text when the AI generates text
- Returns images when the AI generates images  
- Returns both when the AI generates both
- No longer uses embeds, buttons, or style templates

## Original Documentation (for reference only)

### 1. StyleOptionsView - Add Image Button **[UPDATED FOR STITCHED IMAGE FIX]**
**Location**: `bot.py` lines 375-522
**Purpose**: Allow users to add images for combined processing without creating stitched outputs
**Features**:
- **Button**: "📎 Add Image" button added to StyleOptionsView
- **User Flow**: Click button → Instructions sent → User uploads image → Preview updated with combined images
- **Smart Source Detection**: Uses original input images, never stitched images as inputs
- **Ephemeral Display**: Shows combined preview without creating persistent stitched outputs
- **Original Image Tracking**: Updates original_images list for proper processing
- **Error Handling**: Validates image size, handles download failures

### 2. ProcessRequestView - Add Image Button  
**Location**: `bot.py` lines 876-980
**Purpose**: Allow users to add images to requests before processing (text-to-image → text+image)
**Features**:
- **Button**: "📎 Add Image" button added to ProcessRequestView
- **User Flow**: Click button → Instructions sent → User uploads image → Request updated
- **Request Conversion**: Converts text-only requests to text+image requests
- **Preview Update**: Shows updated preview with all images
- **Error Handling**: Same validation and error handling as StyleOptionsView

### 3. Helper Methods Added

#### StyleOptionsView Helper Methods:
- `_process_add_image()`: Handles image download and processing for outputs
- `_get_source_images_for_current_output()`: Extracts source images, avoiding stitched inputs
- `_update_display_after_add()`: Updates display to show new output

#### ProcessRequestView Helper Methods:
- `_process_add_image_to_request()`: Handles image download and addition to requests
- `_update_request_display_after_add()`: Updates request display with new images

## User Experience Flow

### Adding Image to Existing Output (StyleOptionsView):
1. User views generated output (e.g., 2/2 or 4/4)
2. User clicks "📎 Add Image" button
3. Bot sends ephemeral instructions message
4. User uploads image in next message
5. Bot downloads and validates image
6. Bot extracts source images from current output (avoiding stitched images)
7. Bot creates new stitched output combining source + new image
8. Bot updates display to show new output (e.g., 3/3 or 5/5)
9. User's upload message is deleted for cleanup
10. Success message sent to user

### Adding Image to Request (ProcessRequestView):
1. User has text-to-image request ready to process
2. User clicks "📎 Add Image" button
3. Bot sends ephemeral instructions message
4. User uploads image in next message
5. Bot downloads and validates image
6. Bot adds image to request images list
7. Bot updates request display to show text+image mode
8. User can now process with both text and images

## Technical Implementation Details

### Key Design Decisions:
- **No Stitched Inputs**: Implementation carefully avoids using stitched images as inputs
- **Original Image Tracking**: Uses `original_images` field to track source images
- **Async Message Handling**: Uses `client.wait_for('message')` with timeout for image uploads
- **Ephemeral Responses**: User instructions are ephemeral to avoid channel clutter
- **Error Handling**: Comprehensive validation for image size, download, and processing
- **Cleanup**: Deletes user upload messages to keep channel clean

### Example Scenarios Handled:

**Scenario 1**: User viewing output 2/2
- Source: 1 original input image
- Add: 1 new image  
- Result: New output 3/3 with 2 images stitched

**Scenario 2**: User viewing output 4/4 (stitched from 3 original images)
- Source: 3 original input images (not the stitched output)
- Add: 1 new image
- Result: New output 5/5 with 4 images stitched

**Scenario 3**: User in text-to-image mode
- Source: Text prompt only
- Add: 1 image
- Result: Text + image request ready to process

## Files Modified
- `bot.py`: Main implementation (276 lines added)

## Testing
- Unit tests validate core logic
- Manual tests simulate Discord interactions
- All edge cases tested and verified

## Notes for Future Maintenance
- Button placement is consistent with existing UI patterns
- Error handling follows existing patterns in the codebase
- All functionality is backwards compatible
- No breaking changes to existing features