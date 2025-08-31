# Persistent Views Architecture

## Overview

The Nano Banana Discord Bot has been updated to use persistent Discord UI Views to eliminate timeout issues. This ensures that user interactions remain functional indefinitely and survive bot restarts.

## Key Changes

### 1. Timeout Removal
- All View classes now use `timeout=None` instead of the default 300 seconds
- Removed `on_timeout()` methods since views no longer timeout
- Users can interact with buttons/dropdowns without time pressure

### 2. Custom IDs Implementation
Every interactive component now has a stable `custom_id`:

**StyleOptionsView:**
- `style_nav_left` - Navigate to previous output
- `style_nav_right` - Navigate to next output  
- `style_process_prompt` - Process current image with prompt
- `style_edit_prompt` - Edit prompt for generated image
- `style_options_select` - Style dropdown selector

**ProcessRequestView:**
- `process_request_button` - Main process button
- `process_edit_prompt` - Edit prompt button
- `process_style_select` - Style template selector

### 3. Persistent View Registration
In the `on_ready()` event, empty view instances are registered with `bot.add_view()`. This enables the bot to:
- Handle interactions on messages sent before a restart
- Route interactions to correct handlers based on custom_id
- Prevent "This interaction failed" errors

### 4. Safe Interaction Handling
Added `safe_interaction_response()` helper that:
- Handles interaction token expiry gracefully
- Falls back to direct message editing when tokens expire (15 min limit)
- Provides robust error handling for various interaction states

## Benefits

1. **No Timeouts**: Users can take unlimited time to interact with bot messages
2. **Restart Resilience**: Interactions work even after bot restarts
3. **Better UX**: No more "This interaction failed" messages
4. **Token Safety**: Graceful handling of 15-minute interaction token limits

## Technical Details

- Views are created with dynamic data but use stable custom_ids
- Persistent views registered on startup handle routing to appropriate methods
- Safe interaction patterns prevent common Discord API errors
- All changes maintain backward compatibility with existing functionality