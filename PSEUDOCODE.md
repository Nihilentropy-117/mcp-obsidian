# MCP Obsidian Server Pseudocode (Extensively Commented)

## Initialization

```
// Import all required libraries for the application
// - json: For serializing/deserializing data to/from JSON format
// - os: For environment variable access and file system operations
// - pathlib: Modern path manipulation with security features
// - yaml: For parsing .base files and frontmatter in markdown
// - rapidfuzz: Fast fuzzy string matching for search features
// - mcp: Model Context Protocol SDK for Claude integration
// - dotenv: Load configuration from .env file
IMPORT libraries (json, os, pathlib, yaml, rapidfuzz, mcp, dotenv)

// Load environment variables from .env file in project root
// This allows users to configure the vault path without hardcoding
LOAD environment variables from .env file

// Get the VAULT_PATH environment variable which points to the Obsidian vault
// This is the root directory containing all markdown notes and vault files
vault_path = GET environment variable "VAULT_PATH"

// Validate that VAULT_PATH is set - this is a required configuration
// Without a vault path, the server has nothing to serve
IF vault_path is empty:
    RAISE error "VAULT_PATH required"

// Convert the vault path to an absolute resolved path
// .resolve() follows symlinks and makes path absolute
// This ensures consistent path handling throughout the application
vault_root = RESOLVE absolute path of vault_path

// Validate that the vault path exists and is a directory
// Catches configuration errors early before attempting file operations
IF vault_root does not exist OR is not directory:
    RAISE error "Invalid vault path"
```

## Helper Functions

```
// Security-critical function that converts relative paths to absolute paths
// while ensuring they stay within the vault boundary (prevents path traversal)
FUNCTION get_vault_path(relative_path):
    // If a relative path is provided, join it with vault_root
    // Otherwise, just return the vault_root itself
    IF relative_path provided:
        // Combine vault root with user-provided relative path
        // Then resolve to get absolute path (follows symlinks, removes ..)
        full_path = RESOLVE vault_root / relative_path
    ELSE:
        // No relative path means we want the vault root itself
        full_path = RESOLVE vault_root

    // SECURITY CHECK: Ensure the resolved path is still within vault_root
    // This prevents path traversal attacks like "../../../etc/passwd"
    TRY:
        // If full_path is within vault_root, this succeeds
        // relative_to() will throw ValueError if paths don't share common base
        CALCULATE full_path relative to vault_root
    CATCH ValueError:
        // Path escaped vault boundary - reject it
        RAISE error "Path is outside vault"

    // Path is safe - return it for use
    RETURN full_path

// Recursively lists all files and directories in vault structure
// Returns nested dict/list structure matching directory hierarchy
// Used by list_files_in_vault and list_files_in_dir tools
FUNCTION list_vault_files(dirpath):
    // Convert relative dirpath to safe absolute path within vault
    target_path = GET vault_path(dirpath)

    // Validate target path exists and is a directory
    // Fail fast if user requests invalid path
    IF target_path does not exist OR is not directory:
        RAISE error

    // Initialize result list to accumulate files/directories
    result = empty list

    // Iterate through directory contents in sorted order
    // Sorting ensures: directories first (for readability), then alphabetical
    // key=lambda ensures directories appear before files in output
    FOR EACH item IN sorted(target_path.iterdir()):
        // Skip hidden files/directories (starting with '.')
        // This includes .git, .obsidian, .DS_Store, etc.
        // Prevents exposing system files to the client
        IF item.name starts with '.':
            SKIP

        // Handle directories recursively
        IF item is directory:
            // Recursively get contents of subdirectory
            // Calculate relative path from vault_root for recursion
            subdir_contents = RECURSIVELY list_vault_files(item)

            // Only include directories that have content
            // Empty directories are omitted to reduce noise
            IF subdir_contents not empty:
                // Store as dict: {directory_name: [contents]}
                APPEND {item.name: subdir_contents} to result
        ELSE:
            // Regular file - just add the filename string
            APPEND item.name to result

    // Return the nested structure of files and directories
    RETURN result
```

## Tool Handler Base Class

```
// Abstract base class for all MCP tool handlers
// Provides consistent interface for tool registration and execution
// Each tool must implement get_tool_description() and run_tool()
CLASS ToolHandler:
    // Constructor that stores the unique tool name
    // Tool name is used for registration and routing
    FUNCTION __init__(tool_name):
        SET self.name = tool_name

    // Returns MCP Tool schema describing this tool's capabilities
    // Must be implemented by subclasses to define:
    // - name: unique identifier
    // - description: what the tool does
    // - inputSchema: JSON schema for arguments
    FUNCTION get_tool_description():
        RAISE NotImplementedError

    // Executes the tool with given arguments
    // Must be implemented by subclasses to provide actual functionality
    // Arguments validated against inputSchema before this is called
    // Must return Sequence[TextContent | ImageContent | EmbeddedResource]
    FUNCTION run_tool(args):
        RAISE NotImplementedError
```

## List Files Tools

```
// Tool to list all files in the vault root directory
// Useful for discovering vault structure and available notes
CLASS ListFilesInVaultToolHandler(ToolHandler):
    FUNCTION __init__():
        // Register with standard tool name for vault root listing
        CALL parent __init__ with "obsidian_list_files_in_vault"

    // Define tool schema for MCP protocol
    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Lists all files in vault root"
            // No input parameters needed - always lists root
            inputSchema = empty object

    // Execute the tool - list vault root contents
    FUNCTION run_tool(args):
        // Call helper with empty path to list root
        files = CALL list_vault_files()
        // Return as JSON for wire format
        RETURN JSON of files

// Tool to list files in a specific directory within vault
// Allows exploring subdirectories without full vault traversal
CLASS ListFilesInDirToolHandler(ToolHandler):
    FUNCTION __init__():
        // Register with tool name for directory listing
        CALL parent __init__ with "obsidian_list_files_in_dir"

    // Define tool schema requiring dirpath parameter
    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Lists files in specific directory"
            // Requires dirpath: relative path from vault root
            inputSchema = {dirpath: string}

    // Execute the tool - list specific directory
    FUNCTION run_tool(args):
        // Validate required parameter present
        IF dirpath not in args:
            RAISE error

        // List the requested directory
        files = CALL list_vault_files(args.dirpath)
        RETURN JSON of files
```

## File Content Tool

```
// Tool to read and return content of a single file
// Core functionality for accessing note contents
CLASS GetFileContentsToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_get_file_contents"

    // Define tool schema requiring filepath
    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Return content of single file"
            // filepath: relative path from vault root
            // format: path indicates this is a file path string
            inputSchema = {filepath: string}

    FUNCTION run_tool(args):
        // Validate required filepath parameter
        IF filepath not in args:
            RAISE error

        // Convert to safe absolute path within vault
        // get_vault_path ensures no path traversal
        file_path = GET vault_path(args.filepath)

        // Validate file exists and is actually a file (not directory)
        IF file_path does not exist OR is not file:
            RAISE error

        // Read file contents with error handling
        TRY:
            // Read as UTF-8 text (markdown files are UTF-8)
            content = READ file_path as UTF-8 text
        CATCH Exception:
            // Could fail due to permissions, encoding, etc.
            RAISE error

        // Return raw content as TextContent
        RETURN content as TextContent
```

## Search Tool

```
// Simple full-text search across all files in vault
// Finds all occurrences of query string with surrounding context
// More basic than complex_search - just literal string matching
CLASS SearchToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_simple_search"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Simple text search across vault"
            inputSchema = {
                query: string,  // Text to search for
                context_length: integer  // Characters of context (default 100)
            }

    FUNCTION run_tool(args):
        // Validate required query parameter
        IF query not in args:
            RAISE error

        query = args.query
        // Get context_length or default to 100 characters
        // Context shows text before/after match for relevance
        context_length = GET args.context_length OR default 100

        // Accumulate all search results across files
        results = empty list

        // Iterate through every file in vault recursively
        // rglob("*") finds all files at any depth
        FOR EACH file_path IN vault_root.rglob("*"):
            // Skip directories and hidden files
            IF file_path is not file OR name starts with '.':
                SKIP

            TRY:
                // Read file content for searching
                content = READ file_path as UTF-8
                // Get path relative to vault for display
                relative_path = CALCULATE file_path relative to vault_root

                // Accumulate all matches within this file
                matches = empty list

                // Case-insensitive search
                content_lower = LOWERCASE content
                query_lower = LOWERCASE query

                // Current search position in file
                pos = 0

                // Find all occurrences of query in file
                WHILE True:
                    // Find next occurrence starting from pos
                    pos = FIND query_lower in content_lower starting at pos

                    // No more matches in this file
                    IF pos == -1:
                        BREAK

                    // Extract context around match
                    // Ensure we don't go before start of file
                    start = MAX(0, pos - context_length)
                    // Ensure we don't go past end of file
                    end = MIN(length of content, pos + length of query + context_length)
                    // Get the context substring (preserves original case)
                    context = SUBSTRING of content from start to end

                    // Store match with context and position
                    APPEND {
                        context,  // Text surrounding the match
                        match_position: {
                            start: pos,  // Absolute position in file
                            end: pos + length  // End of match
                        }
                    } to matches

                    // Move to next character to find overlapping matches
                    // This finds "AAA" twice in "AAAA"
                    INCREMENT pos

                // If file had any matches, include it in results
                IF matches not empty:
                    APPEND {
                        filename: relative_path,
                        score: count of matches,  // Relevance score
                        matches  // All match details
                    } to results

            CATCH UnicodeDecodeError OR PermissionError:
                // Skip binary files or files we can't read
                // Don't fail entire search for one bad file
                SKIP

        // Return all results as JSON
        RETURN JSON of results
```

## File Modification Tools

```
// Tool to append content to end of existing or new file
// Useful for adding to daily notes, logs, etc.
CLASS AppendContentToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_append_content"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Append content to file"
            inputSchema = {
                filepath: string,  // File to append to
                content: string    // Content to add at end
            }

    FUNCTION run_tool(args):
        // Validate both required parameters present
        IF filepath OR content not in args:
            RAISE error

        // Get safe path within vault
        file_path = GET vault_path(args.filepath)

        // Create parent directories if they don't exist
        // Allows creating files in new folders
        CREATE parent directories if needed

        TRY:
            // Open in append mode - cursor at end of file
            // Creates file if it doesn't exist
            OPEN file_path in append mode:
                WRITE args.content
        CATCH Exception:
            // Could fail due to permissions, disk space, etc.
            RAISE error

        RETURN success message

// Tool to create new file or completely overwrite existing file
// Unlike append, this replaces entire content
CLASS PutContentToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_put_content"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Create or update file content"
            inputSchema = {
                filepath: string,  // Target file path
                content: string    // Complete new content
            }

    FUNCTION run_tool(args):
        // Validate required parameters
        IF filepath OR content not in args:
            RAISE error

        file_path = GET vault_path(args.filepath)
        // Ensure parent directory exists
        CREATE parent directories if needed

        TRY:
            // Write mode - truncates file if exists, creates if not
            WRITE args.content to file_path
        CATCH Exception:
            RAISE error

        RETURN success message

// Tool to delete a file or directory from vault
// Requires explicit confirmation to prevent accidents
CLASS DeleteFileToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_delete_file"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Delete file or directory"
            inputSchema = {
                filepath: string,    // Path to delete
                confirm: boolean     // Must be true to proceed
            }

    FUNCTION run_tool(args):
        // Validate filepath present
        IF filepath not in args:
            RAISE error

        // SAFETY: Require explicit confirmation
        // Prevents accidental deletions from confused prompts
        IF confirm is not true:
            RAISE error "Confirmation required"

        file_path = GET vault_path(args.filepath)

        // Check target exists before attempting deletion
        IF file_path does not exist:
            RAISE error

        TRY:
            // Different deletion for directories vs files
            IF file_path is directory:
                // Recursively delete directory and all contents
                RECURSIVELY DELETE file_path
            ELSE:
                // Delete single file
                DELETE file_path
        CATCH Exception:
            // Could fail due to permissions, open files, etc.
            RAISE error

        RETURN success message
```

## Patch Content Tool

```
// Advanced tool to modify files by inserting content relative to landmarks
// Supports three target types: headings, blocks, frontmatter
// Three operations: append, prepend, replace
CLASS PatchContentToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_patch_content"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Insert content relative to heading/frontmatter"
            inputSchema = {
                filepath,      // File to modify
                operation,     // append/prepend/replace
                target_type,   // heading/block/frontmatter
                target,        // Specific heading/field name
                content        // Content to insert
            }

    FUNCTION run_tool(args):
        // Validate all required parameters present
        IF any required arg missing:
            RAISE error

        file_path = GET vault_path(args.filepath)

        // File must exist for patching
        IF file_path does not exist OR is not file:
            RAISE error

        TRY:
            // Read entire file into memory for modification
            // NOTE: Not suitable for very large files
            content = READ file_path

            // Split into lines for line-based manipulation
            lines = SPLIT content by newlines

            operation = args.operation      // append/prepend/replace
            target_type = args.target_type  // heading/block/frontmatter
            target = args.target            // Which heading/field
            new_content = args.content      // What to insert

            // CASE: Modifying content relative to a heading
            IF target_type is "heading":
                // Extract heading level from # markers
                // "## Title" -> level 2
                target_level = COUNT '#' in target
                // Get text without # markers for matching
                target_text = STRIP '#' from target

                // Search for matching heading in file
                FOR i, line IN enumerate(lines):
                    // Check if line is a heading and matches target
                    IF line starts with '#' AND target_text in LOWERCASE line:
                        // OPERATION: Insert before heading content
                        IF operation is "prepend":
                            // Insert right after heading line
                            INSERT new_content at position i + 1

                        // OPERATION: Insert after heading section ends
                        ELSE IF operation is "append":
                            // Find where this heading's section ends
                            j = i + 1
                            WHILE j < length of lines:
                                // Next heading of same/higher level ends section
                                IF lines[j] starts with '#':
                                    // Calculate level of this heading
                                    heading_level = CALCULATE heading level
                                    // Same or higher level = new section
                                    IF heading_level <= target_level:
                                        BREAK
                                INCREMENT j
                            // Insert at end of section
                            INSERT new_content at position j

                        // OPERATION: Replace entire heading line
                        ELSE IF operation is "replace":
                            SET lines[i] = new_content

                        // Found and modified - stop searching
                        BREAK

            // CASE: Modifying YAML frontmatter at top of file
            ELSE IF target_type is "frontmatter":
                // Frontmatter is YAML between --- markers
                IF lines[0] is "---":
                    // Find closing --- marker
                    end_idx = 1
                    WHILE end_idx < length AND lines[end_idx] != "---":
                        INCREMENT end_idx

                    // OPERATION: Add new field to frontmatter
                    IF operation is "append" OR "prepend":
                        // Insert as "key: value" format
                        INSERT "{target}: {new_content}" at end_idx

                    // OPERATION: Replace existing field value
                    ELSE IF operation is "replace":
                        // Search for field in frontmatter
                        FOR i FROM 1 TO end_idx:
                            // Field found - replace its value
                            IF lines[i] starts with "{target}:":
                                SET lines[i] = "{target}: {new_content}"
                                BREAK

            // Write modified lines back to file
            WRITE JOIN(lines, newline) to file_path

        CATCH Exception:
            RAISE error

        RETURN success message
```

## Complex Search Tool

```
// Advanced search supporting glob patterns and regular expressions
// Can combine multiple conditions with AND/OR logic
// More powerful than simple_search for sophisticated queries
CLASS ComplexSearchToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_complex_search"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Complex search with glob/regex patterns"
            // Query is object containing nested search conditions
            inputSchema = {query: object}

    FUNCTION run_tool(args):
        // Validate query present
        IF query not in args:
            RAISE error

        query = args.query  // Can be nested AND/OR/glob/regexp
        results = empty list

        // Scan entire vault for matches
        FOR EACH file_path IN vault_root.rglob("*"):
            // Skip non-files and hidden files
            IF file_path is not file OR name starts with '.':
                SKIP

            // Get relative path for matching and display
            relative_path = CALCULATE file_path relative to vault_root

            TRY:
                // Read file content for content-based patterns
                content = READ file_path

                // Evaluate query against this file
                // Recursively handles nested AND/OR/glob/regexp
                IF CALL _matches_query(query, relative_path, content):
                    // File matches - include in results
                    APPEND relative_path to results

            CATCH UnicodeDecodeError OR PermissionError:
                // Skip unreadable files
                SKIP

        RETURN JSON of results

    // Recursively evaluate search query against file
    // Supports: AND, OR, glob (filename patterns), regexp (content patterns)
    FUNCTION _matches_query(query, path, content):
        // OPERATOR: All conditions must match
        IF "and" in query:
            // Recursively check each sub-condition
            // Return true only if ALL match
            RETURN ALL of [_matches_query(q, path, content) FOR q IN query.and]

        // OPERATOR: Any condition can match
        ELSE IF "or" in query:
            // Recursively check each sub-condition
            // Return true if ANY match
            RETURN ANY of [_matches_query(q, path, content) FOR q IN query.or]

        // OPERATOR: Glob pattern matching (like *.md, Work/*)
        ELSE IF "glob" in query:
            pattern, target = query.glob
            // Match against path or content based on target
            value = path IF target is "path" ELSE content
            // fnmatch does Unix-style glob matching
            RETURN fnmatch(value, pattern)

        // OPERATOR: Regular expression matching
        ELSE IF "regexp" in query:
            pattern, target = query.regexp
            // Match against path or content based on target
            value = path IF target is "path" ELSE content
            // Use regex engine to test pattern
            RETURN regex.search(pattern, value) is not null

        // Unknown operator - no match
        RETURN False
```

## Batch Get Files Tool

```
// Efficiently read multiple files in one request
// Returns all contents concatenated with headers and separators
// Reduces round-trips for reading related files
CLASS BatchGetFileContentsToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_batch_get_file_contents"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Return contents of multiple files"
            // filepaths is array of file paths to read
            inputSchema = {filepaths: array of strings}

    FUNCTION run_tool(args):
        // Validate filepaths array present
        IF filepaths not in args:
            RAISE error

        // Accumulate all file contents
        result = empty list

        // Process each requested file
        FOR EACH filepath IN args.filepaths:
            TRY:
                // Get safe path within vault
                file_path = GET vault_path(filepath)
                // Read file content
                content = READ file_path
                // Format with header, content, separator
                // Makes it easy to identify which file is which
                APPEND "# {filepath}\n\n{content}\n\n---\n\n" to result
            CATCH Exception as e:
                // Include error in output but continue processing
                // Don't fail entire batch for one bad file
                APPEND "# {filepath}\n\nError: {e}\n\n---\n\n" to result

        // Concatenate all file contents
        RETURN JOIN(result)
```

## Periodic Notes Tools

```
// Get current periodic note (daily, weekly, monthly, etc.)
// Searches common locations for periodic note files
// Based on current date to determine which file to find
CLASS PeriodicNotesToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_get_periodic_note"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Get current periodic note"
            inputSchema = {
                period: enum,  // daily/weekly/monthly/quarterly/yearly
                type: enum     // content/metadata
            }

    FUNCTION run_tool(args):
        // Validate period parameter
        IF period not in args:
            RAISE error

        period = args.period
        // Type determines return format
        type_arg = GET args.type OR "content"

        // Get current date/time for filename generation
        now = CURRENT datetime

        // Generate expected filename based on period type
        // Each period has different naming convention
        IF period is "daily":
            // Format: 2024-01-15.md
            filename = FORMAT now as "YYYY-MM-DD.md"
        ELSE IF period is "weekly":
            // Format: 2024-W03.md (ISO week number)
            filename = FORMAT now as "YYYY-Www.md"
        ELSE IF period is "monthly":
            // Format: 2024-01.md
            filename = FORMAT now as "YYYY-MM.md"
        ELSE IF period is "quarterly":
            // Calculate which quarter (1-4)
            quarter = CALCULATE (now.month - 1) / 3 + 1
            // Format: 2024-Q1.md
            filename = "YYYY-Qq.md"
        ELSE IF period is "yearly":
            // Format: 2024.md
            filename = FORMAT now as "YYYY.md"
        ELSE:
            // Unknown period type
            RAISE error

        // Try common locations for periodic notes
        // Different users organize periodic notes differently
        search_paths = [
            filename,                      // Root of vault
            "Daily/{filename}",            // Daily subfolder
            "Periodic/{filename}",         // Periodic subfolder
            "Journal/{filename}",          // Journal subfolder
            "{period.capitalize()}/{filename}"  // Period-specific folder
        ]

        // Search each location until we find the note
        FOR EACH search_path IN search_paths:
            TRY:
                file_path = GET vault_path(search_path)
                // Check if file exists at this location
                IF file_path exists:
                    content = READ file_path

                    // Return format based on type parameter
                    IF type_arg is "metadata":
                        // Include path, content, and modification time
                        RETURN JSON {
                            path: search_path,
                            content: content,
                            mtime: file_path.stat().mtime
                        }
                    ELSE:
                        // Just return raw content
                        RETURN content
            CATCH Exception:
                // This location doesn't exist - try next one
                CONTINUE

        // Checked all locations - note not found
        RAISE error "Periodic note not found"

// Get list of recent periodic notes of specified type
// Returns most recently modified notes for the period
CLASS RecentPeriodicNotesToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_get_recent_periodic_notes"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Get recent periodic notes"
            inputSchema = {
                period: enum,           // daily/weekly/monthly/quarterly/yearly
                limit: int,             // Max number to return
                include_content: bool   // Whether to include note text
            }

    FUNCTION run_tool(args):
        // Validate period
        IF period not in args:
            RAISE error

        period = args.period
        limit = GET args.limit OR 5  // Default to 5 notes
        include_content = GET args.include_content OR False

        // Define regex patterns to match periodic note filenames
        // Each period type has specific format
        patterns = {
            "daily": regex "\d{4}-\d{2}-\d{2}\.md",      // 2024-01-15.md
            "weekly": regex "\d{4}-W\d{2}\.md",          // 2024-W03.md
            "monthly": regex "\d{4}-\d{2}\.md",          // 2024-01.md
            "quarterly": regex "\d{4}-Q[1-4]\.md",       // 2024-Q1.md
            "yearly": regex "\d{4}\.md"                  // 2024.md
        }

        // Get pattern for requested period type
        pattern = GET patterns[period]
        IF pattern is null:
            RAISE error

        // Find all files matching pattern anywhere in vault
        matching_files = empty list

        FOR EACH file_path IN vault_root.rglob("*.md"):
            // Check if filename matches periodic note pattern
            IF REGEX MATCH pattern on file_path.name:
                APPEND file_path to matching_files

        // Sort by modification time, most recent first
        // Assumes modification time indicates most recent edit
        SORT matching_files BY modification time DESCENDING

        // Limit to requested number of results
        matching_files = TAKE first limit items

        // Build result list with metadata
        results = empty list
        FOR EACH file_path IN matching_files:
            // Get path relative to vault for display
            relative_path = CALCULATE file_path relative to vault_root

            // Start with path and modification time
            result = {
                path: relative_path,
                mtime: file_path.stat().mtime
            }

            // Optionally include full content
            IF include_content:
                TRY:
                    result.content = READ file_path
                CATCH Exception:
                    // If read fails, set content to null
                    result.content = null

            APPEND result to results

        RETURN JSON of results
```

## Recent Changes Tool

```
// Find files modified within specified time window
// Useful for seeing what's been worked on recently
CLASS RecentChangesToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_get_recent_changes"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Get recently modified files"
            inputSchema = {
                limit: int,  // Max files to return (default 10)
                days: int    // Only files modified in last N days (default 90)
            }

    FUNCTION run_tool(args):
        limit = GET args.limit OR 10   // Default 10 files
        days = GET args.days OR 90     // Default 90 day window

        // Calculate cutoff timestamp
        // Files older than this are excluded
        cutoff_time = CALCULATE (now - timedelta(days)).timestamp()

        recent_files = empty list

        // Scan all files in vault
        FOR EACH file_path IN vault_root.rglob("*"):
            // Skip non-files and hidden files
            IF file_path is not file OR name starts with '.':
                SKIP

            // Get file's last modification time
            mtime = GET file_path modification time

            // Include if modified after cutoff
            IF mtime >= cutoff_time:
                APPEND {
                    path: relative_path,
                    mtime: mtime
                } to recent_files

        // Sort by modification time, newest first
        SORT recent_files BY mtime DESCENDING

        // Limit to requested number
        recent_files = TAKE first limit items

        RETURN JSON of recent_files
```

## Fuzzy Search Tool

```
// Search files using fuzzy string matching
// Tolerates typos and partial matches in filenames/content
// Uses rapidfuzz library for efficient fuzzy matching
CLASS FuzzySearchToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_fuzzy_search"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Fuzzy search for files by filename"
            inputSchema = {
                query: string,          // What to search for
                limit: int,             // Max results (default 10)
                score_threshold: number, // Min similarity 0-100 (default 60)
                search_content: bool    // Also search file contents (slower)
            }

    FUNCTION run_tool(args):
        // Validate query
        IF query not in args:
            RAISE error

        query = args.query
        limit = GET args.limit OR 10
        score_threshold = GET args.score_threshold OR 60  // 60% similarity
        search_content = GET args.search_content OR False

        // Collect all file paths first
        file_paths = empty list
        FOR EACH file_path IN vault_root.rglob("*"):
            // Only include regular files, not hidden
            IF file_path is file AND name does not start with '.':
                APPEND relative_path to file_paths

        results = empty list

        // MODE 1: Search both filenames and content (slower)
        IF search_content:
            // Process each file individually
            FOR EACH file_path_str IN file_paths:
                // First try matching filename
                // WRatio is weighted ratio algorithm - handles different length strings
                filename_score = FUZZY MATCH query TO file_path_str

                // Good filename match - include it
                IF filename_score >= score_threshold:
                    APPEND {
                        filepath: file_path_str,
                        score: filename_score,
                        match_type: "filename"
                    } to results
                ELSE:
                    // Filename didn't match - try content
                    TRY:
                        file_path = GET vault_path(file_path_str)
                        content = READ file_path

                        IF content not empty:
                            // partial_ratio finds best substring match
                            // Good for finding query anywhere in content
                            content_score = FUZZY PARTIAL MATCH query TO content

                            // Good content match - include it
                            IF content_score >= score_threshold:
                                APPEND {
                                    filepath: file_path_str,
                                    score: content_score,
                                    match_type: "content"
                                } to results
                    CATCH Exception:
                        // Skip unreadable files
                        SKIP

        // MODE 2: Search filenames only (faster)
        ELSE:
            // Use process.extract for efficient batch fuzzy matching
            // Returns top matches above threshold
            // limit * 2 to get extra results for filtering
            matches = FUZZY PROCESS.EXTRACT(
                query,
                file_paths,
                scorer=WRatio,
                limit=limit * 2,
                score_cutoff=score_threshold
            )

            // Convert to result format
            results = [
                {
                    filepath: match[0],      // File path
                    score: match[1],         // Similarity score
                    match_type: "filename"
                }
                FOR match IN matches
            ]

        // Sort by similarity score, best matches first
        SORT results BY score DESCENDING

        // Limit to requested number of results
        results = TAKE first limit items

        RETURN JSON of results
```

## List Bases Tool

```
// List all Obsidian Bases (.base files) in vault
// Bases are database-like views with filters and columns
// This tool discovers bases and extracts their structure
CLASS ListBasesToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_list_bases"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "List all .base files with their structure"
            // No parameters - lists all bases
            inputSchema = empty object

    FUNCTION run_tool(args):
        // Find all .base files anywhere in vault
        base_files = empty list
        FOR EACH file_path IN vault_root.rglob("*.base"):
            // Skip hidden files
            IF name does not start with '.':
                APPEND file_path to base_files

        // Parse each base file to extract structure
        bases_info = empty list
        FOR EACH base_path IN base_files:
            TRY:
                // Read base file content (YAML format)
                content = READ base_path
                relative_path = CALCULATE base_path relative to vault_root

                IF content not empty:
                    // Parse YAML to get base configuration
                    base_config = PARSE YAML content

                    // Extract properties used in filters
                    // Filters define which notes belong to this base
                    filter_properties = empty set
                    IF "filters" in base_config:
                        // Convert filters to string for regex extraction
                        filter_str = STRING base_config.filters

                        // Find property names using regex
                        // Looks for words before comparison operators
                        // Matches: file.folder, tags, type, status, etc.
                        property_matches = REGEX FINDALL r'[\w\.]+(?=\s*[=<>!])' IN filter_str
                        ADD property_matches to filter_properties

                    // Extract view configurations
                    // Views define different ways to display the data
                    all_columns = empty set
                    views_info = empty list
                    IF "views" in base_config AND is list:
                        // Process each view definition
                        FOR EACH view IN base_config.views:
                            view_name = GET view.name OR "Unnamed"
                            view_type = GET view.type OR "table"
                            columns = GET view.order OR empty list

                            // Accumulate all unique columns across views
                            ADD columns to all_columns

                            // Store view metadata
                            APPEND {
                                name: view_name,
                                type: view_type,
                                columns: columns
                            } to views_info

                    // Store complete base information
                    APPEND {
                        filepath: relative_path,
                        name: base_path.stem,  // Filename without extension
                        filters: base_config.filters,
                        filter_properties: SORTED LIST of filter_properties,
                        views: views_info,
                        all_columns: SORTED LIST of all_columns
                    } to bases_info

            CATCH Exception as e:
                // If we can't parse a base, include it with error
                // Don't fail entire listing for one bad base
                APPEND {
                    filepath: relative_path,
                    name: base_path.stem,
                    error: "Failed to parse: {e}"
                } to bases_info

        RETURN JSON of bases_info
```

## Search Bases Tool

```
// Search for notes within a specific Obsidian Base
// Applies base's filters and optional additional property filters
// Returns matching notes with their properties
CLASS SearchBasesToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_search_bases"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Search notes within specific base"
            inputSchema = {
                base_name: string,          // Which base to search
                property_filters: object,   // Additional filters
                include_content: bool,      // Include note text
                limit: int                  // Max results (default 50)
            }

    FUNCTION run_tool(args):
        // Validate base name provided
        IF base_name not in args:
            RAISE error

        base_name = args.base_name
        property_filters = GET args.property_filters OR empty dict
        include_content = GET args.include_content OR False
        limit = GET args.limit OR 50

        // Find the .base file by name
        base_path = null
        FOR EACH file_path IN vault_root.rglob("{base_name}.base"):
            IF name does not start with '.':
                base_path = file_path
                BREAK

        // Base not found in vault
        IF base_path is null:
            RAISE error "Base not found"

        // Read and parse base configuration
        content = READ base_path
        IF content is empty:
            RAISE error

        base_config = PARSE YAML content

        // Extract folder filter from base definition
        // Most bases filter by file.folder to limit scope
        target_folder = null
        IF "filters" in base_config:
            filters = base_config.filters
            IF filters is dict:
                // Get AND conditions from filters
                and_conditions = GET filters.and OR empty list
                FOR EACH condition IN and_conditions:
                    // Look for file.folder condition
                    IF condition is string AND "file.folder" in condition:
                        // Extract folder path using regex
                        // Matches: file.folder == "Files/Places"
                        match = REGEX SEARCH r'file\.folder\s*==\s*["\']([^"\']+)["\']' IN condition
                        IF match:
                            target_folder = match.group(1)

        // Get markdown files from target location
        IF target_folder:
            // Search only within specified folder
            search_path = GET vault_path(target_folder)
            IF search_path exists:
                md_files = LIST search_path.rglob("*.md")
            ELSE:
                // Folder doesn't exist - no results
                md_files = empty list
        ELSE:
            // No folder filter - search entire vault
            md_files = LIST vault_root.rglob("*.md")

        // Filter files based on properties
        results = empty list

        // Get more files than limit to account for filtering
        FOR EACH file_path IN FIRST limit * 2 OF md_files:
            // Skip hidden files
            IF file_path.name starts with '.':
                SKIP

            TRY:
                // Read file to extract frontmatter properties
                file_content = READ file_path

                // Parse YAML frontmatter
                // Frontmatter is metadata at start of markdown files
                properties = empty dict
                IF file_content starts with "---":
                    // Split by --- markers to extract frontmatter
                    parts = SPLIT file_content BY "---" (max 3 parts)
                    IF length of parts >= 3:
                        // Middle part is YAML frontmatter
                        frontmatter = parts[1]
                        TRY:
                            // Parse YAML to get properties dict
                            properties = PARSE YAML frontmatter OR empty dict
                        CATCH Exception:
                            // Invalid YAML - use empty properties
                            properties = empty dict

                // Apply property filters
                matches = True
                IF property_filters not empty:
                    // Check each filter condition
                    FOR EACH prop_key, prop_value IN property_filters:
                        // Property must exist in note
                        IF prop_key not in properties:
                            matches = False
                            BREAK

                        actual_value = properties[prop_key]

                        // For strings: partial case-insensitive match
                        IF prop_value is string AND actual_value is string:
                            IF LOWERCASE prop_value not in LOWERCASE actual_value:
                                matches = False
                                BREAK
                        // For other types: exact match
                        ELSE IF actual_value != prop_value:
                            matches = False
                            BREAK

                // Note matches all filters
                IF matches:
                    result = {
                        filepath: relative_path,
                        properties: properties
                    }

                    // Optionally include content
                    IF include_content:
                        // Remove frontmatter from content
                        IF file_content starts with "---":
                            parts = SPLIT file_content BY "---" (max 3 parts)
                            IF length of parts >= 3:
                                // Third part is content after frontmatter
                                result.content = STRIP parts[2]
                        ELSE:
                            // No frontmatter - all content
                            result.content = file_content

                    APPEND result to results

                    // Stop when we have enough results
                    IF length of results >= limit:
                        BREAK

            CATCH Exception:
                // Skip files we can't read
                SKIP

        // Return results with metadata
        RETURN JSON {
            base: base_name,
            total_results: COUNT of results,
            results: results
        }
```

## MCP Server Setup

```
// Create the main MCP server instance
// "mcp-obsidian" is the server name visible to clients
CREATE Server instance "mcp-obsidian"

// Registry of all tool handlers
// Maps tool name -> handler instance
CREATE tool_handlers empty dict

// Register a tool handler in the registry
// Allows lookup by tool name during execution
FUNCTION add_tool_handler(tool_class):
    // Use tool name as key for fast lookup
    SET tool_handlers[tool_class.name] = tool_class

// Retrieve a tool handler by name
// Returns null if tool doesn't exist
FUNCTION get_tool_handler(name):
    IF name not in tool_handlers:
        RETURN null
    RETURN tool_handlers[name]

// Register all 16 tool handlers with the server
// Order doesn't matter - looked up by name
REGISTER all tool handlers:
    CALL add_tool_handler(ListFilesInDirToolHandler)
    CALL add_tool_handler(ListFilesInVaultToolHandler)
    CALL add_tool_handler(GetFileContentsToolHandler)
    CALL add_tool_handler(SearchToolHandler)
    CALL add_tool_handler(PatchContentToolHandler)
    CALL add_tool_handler(AppendContentToolHandler)
    CALL add_tool_handler(PutContentToolHandler)
    CALL add_tool_handler(DeleteFileToolHandler)
    CALL add_tool_handler(ComplexSearchToolHandler)
    CALL add_tool_handler(BatchGetFileContentsToolHandler)
    CALL add_tool_handler(PeriodicNotesToolHandler)
    CALL add_tool_handler(RecentPeriodicNotesToolHandler)
    CALL add_tool_handler(RecentChangesToolHandler)
    CALL add_tool_handler(FuzzySearchToolHandler)
    CALL add_tool_handler(ListBasesToolHandler)
    CALL add_tool_handler(SearchBasesToolHandler)

// MCP endpoint: Return list of available tools
// Called by client to discover server capabilities
ASYNC FUNCTION list_tools():
    // Get schema from each registered handler
    // Returns array of Tool objects describing capabilities
    RETURN [th.get_tool_description() FOR th IN tool_handlers.values()]

// MCP endpoint: Execute a tool with given arguments
// Main entry point for all tool invocations
ASYNC FUNCTION call_tool(name, arguments):
    // Validate arguments are in expected format
    // MCP protocol requires dict of named arguments
    IF arguments is not dict:
        RAISE error "Arguments must be dictionary"

    // Look up handler for requested tool
    tool_handler = GET tool_handler(name)
    IF tool_handler is null:
        // Tool doesn't exist
        RAISE error "Unknown tool"

    // Execute tool with error handling
    TRY:
        // Delegate to handler's run_tool method
        RETURN CALL tool_handler.run_tool(arguments)
    CATCH Exception as e:
        // Log full error server-side for debugging
        LOG error
        // Return sanitized error to client
        RAISE error with exception message

// Main server entry point
// Sets up stdio transport and runs event loop
ASYNC FUNCTION main():
    // Import stdio server transport
    // Handles communication over stdin/stdout
    IMPORT stdio_server from mcp.server.stdio

    // Create stdio transport streams
    // read_stream: receives requests from client
    // write_stream: sends responses to client
    ASYNC WITH stdio_server() as (read_stream, write_stream):
        // Run the MCP server event loop
        // Processes requests until shutdown
        AWAIT app.run(
            read_stream,
            write_stream,
            initialization_options  // Server capabilities
        )
```

## Entry Point

```
// Python main entry point
// When module is run as script, start the server
IF module is main:
    // Run async main function in asyncio event loop
    CALL asyncio.run(main())
```
