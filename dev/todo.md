# TODO

## Completed Tasks

### 1. Add PERM_SUMMER_2025 support
- ✅ Added PERM_SUMMER_2025 to city mappings in CRM router
- ✅ Added PERM_SUMMER_2025 to city mappings in app.py
- ✅ Fixed linter error in CRM router (null check for message.from_user)
- ✅ Added simple enabled/disabled mechanism with ENABLED_CITIES dict
- ✅ Updated registration flow to only show enabled cities
- ✅ Updated info command to only show enabled cities
- ✅ Updated status command to check for enabled events
- ✅ Updated start handler to work with enabled cities

### 2. Fix payment proof forwarding issues
- ✅ Added city code mapping to avoid special characters in callback data
- ✅ Updated callback data creation to use city codes instead of full city names
- ✅ Updated callback handlers to convert city codes back to full names
- ✅ Added detailed logging to payment forwarding process
- ✅ Fixed exception handlers to re-raise errors (preserve botspot error handling)
- ✅ Added logging for callback data creation and processing
- ✅ Fixed callback data parsing to handle underscores in city codes (PERM_SUMMER)
- ✅ Created proper parse_payment_callback_data() function for maintainable parsing
- ✅ Refactored callback handlers to use the new parsing function

### 3. Fix CRM city selection
- ✅ Added PERM_SUMMER_2025 to CRM city selection choices
- ✅ Updated city selection to only show enabled cities
- ✅ Added dynamic city choice generation based on enabled cities
- ✅ Refactored to use TargetCity enum values instead of hardcoded strings
- ✅ Added loop over TargetCity enum for dynamic city generation

## Future Tasks

### 3. Rework TargetCity concept into "meeting/event"
- Convert TargetCity enum to include both city and date information
- Create a new Event/Meeting model that includes:
  - City
  - Date
  - Time
  - Venue
  - Address
  - Enabled/disabled status
  - Unique id

### 4. Improve enabled/disabled mechanism
- Move from hardcoded ENABLED_CITIES dict to database configuration
- Add admin commands to enable/disable events
- Add proper event management interface

### 5. General improvements
- Add proper event management system
- Add event creation/editing capabilities
- Add event scheduling system
- Improve city/event selection UI 