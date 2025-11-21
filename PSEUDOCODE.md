# MCP Obsidian Server Pseudocode

## Initialization

```
IMPORT libraries (json, os, pathlib, yaml, rapidfuzz, mcp, dotenv)

LOAD environment variables from .env file

vault_path = GET environment variable "VAULT_PATH"
IF vault_path is empty:
    RAISE error "VAULT_PATH required"

vault_root = RESOLVE absolute path of vault_path
IF vault_root does not exist OR is not directory:
    RAISE error "Invalid vault path"
```

## Helper Functions

```
FUNCTION get_vault_path(relative_path):
    IF relative_path provided:
        full_path = RESOLVE vault_root / relative_path
    ELSE:
        full_path = RESOLVE vault_root

    TRY:
        CALCULATE full_path relative to vault_root
    CATCH ValueError:
        RAISE error "Path is outside vault"

    RETURN full_path

FUNCTION list_vault_files(dirpath):
    target_path = GET vault_path(dirpath)

    IF target_path does not exist OR is not directory:
        RAISE error

    result = empty list

    FOR EACH item IN sorted(target_path.iterdir()):
        IF item.name starts with '.':
            SKIP

        IF item is directory:
            subdir_contents = RECURSIVELY list_vault_files(item)
            IF subdir_contents not empty:
                APPEND {item.name: subdir_contents} to result
        ELSE:
            APPEND item.name to result

    RETURN result
```

## Tool Handler Base Class

```
CLASS ToolHandler:
    FUNCTION __init__(tool_name):
        SET self.name = tool_name

    FUNCTION get_tool_description():
        RAISE NotImplementedError

    FUNCTION run_tool(args):
        RAISE NotImplementedError
```

## List Files Tools

```
CLASS ListFilesInVaultToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_list_files_in_vault"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Lists all files in vault root"
            inputSchema = empty object

    FUNCTION run_tool(args):
        files = CALL list_vault_files()
        RETURN JSON of files

CLASS ListFilesInDirToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_list_files_in_dir"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Lists files in specific directory"
            inputSchema = {dirpath: string}

    FUNCTION run_tool(args):
        IF dirpath not in args:
            RAISE error
        files = CALL list_vault_files(args.dirpath)
        RETURN JSON of files
```

## File Content Tool

```
CLASS GetFileContentsToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_get_file_contents"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Return content of single file"
            inputSchema = {filepath: string}

    FUNCTION run_tool(args):
        IF filepath not in args:
            RAISE error

        file_path = GET vault_path(args.filepath)

        IF file_path does not exist OR is not file:
            RAISE error

        TRY:
            content = READ file_path as UTF-8 text
        CATCH Exception:
            RAISE error

        RETURN content as TextContent
```

## Search Tool

```
CLASS SearchToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_simple_search"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Simple text search across vault"
            inputSchema = {query: string, context_length: integer}

    FUNCTION run_tool(args):
        IF query not in args:
            RAISE error

        query = args.query
        context_length = GET args.context_length OR default 100
        results = empty list

        FOR EACH file_path IN vault_root.rglob("*"):
            IF file_path is not file OR name starts with '.':
                SKIP

            TRY:
                content = READ file_path as UTF-8
                relative_path = CALCULATE file_path relative to vault_root
                matches = empty list
                content_lower = LOWERCASE content
                query_lower = LOWERCASE query
                pos = 0

                WHILE True:
                    pos = FIND query_lower in content_lower starting at pos
                    IF pos == -1:
                        BREAK

                    start = MAX(0, pos - context_length)
                    end = MIN(length of content, pos + length of query + context_length)
                    context = SUBSTRING of content from start to end

                    APPEND {context, match_position: {start: pos, end: pos + length}} to matches
                    INCREMENT pos

                IF matches not empty:
                    APPEND {filename: relative_path, score: count of matches, matches} to results

            CATCH UnicodeDecodeError OR PermissionError:
                SKIP

        RETURN JSON of results
```

## File Modification Tools

```
CLASS AppendContentToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_append_content"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Append content to file"
            inputSchema = {filepath: string, content: string}

    FUNCTION run_tool(args):
        IF filepath OR content not in args:
            RAISE error

        file_path = GET vault_path(args.filepath)
        CREATE parent directories if needed

        TRY:
            OPEN file_path in append mode:
                WRITE args.content
        CATCH Exception:
            RAISE error

        RETURN success message

CLASS PutContentToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_put_content"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Create or update file content"
            inputSchema = {filepath: string, content: string}

    FUNCTION run_tool(args):
        IF filepath OR content not in args:
            RAISE error

        file_path = GET vault_path(args.filepath)
        CREATE parent directories if needed

        TRY:
            WRITE args.content to file_path
        CATCH Exception:
            RAISE error

        RETURN success message

CLASS DeleteFileToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_delete_file"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Delete file or directory"
            inputSchema = {filepath: string, confirm: boolean}

    FUNCTION run_tool(args):
        IF filepath not in args:
            RAISE error

        IF confirm is not true:
            RAISE error "Confirmation required"

        file_path = GET vault_path(args.filepath)

        IF file_path does not exist:
            RAISE error

        TRY:
            IF file_path is directory:
                RECURSIVELY DELETE file_path
            ELSE:
                DELETE file_path
        CATCH Exception:
            RAISE error

        RETURN success message
```

## Patch Content Tool

```
CLASS PatchContentToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_patch_content"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Insert content relative to heading/frontmatter"
            inputSchema = {filepath, operation, target_type, target, content}

    FUNCTION run_tool(args):
        IF any required arg missing:
            RAISE error

        file_path = GET vault_path(args.filepath)

        IF file_path does not exist OR is not file:
            RAISE error

        TRY:
            content = READ file_path
            lines = SPLIT content by newlines
            operation = args.operation
            target_type = args.target_type
            target = args.target
            new_content = args.content

            IF target_type is "heading":
                target_level = COUNT '#' in target
                target_text = STRIP '#' from target

                FOR i, line IN enumerate(lines):
                    IF line starts with '#' AND target_text in LOWERCASE line:
                        IF operation is "prepend":
                            INSERT new_content at position i + 1
                        ELSE IF operation is "append":
                            j = i + 1
                            WHILE j < length of lines:
                                IF lines[j] starts with '#':
                                    heading_level = CALCULATE heading level
                                    IF heading_level <= target_level:
                                        BREAK
                                INCREMENT j
                            INSERT new_content at position j
                        ELSE IF operation is "replace":
                            SET lines[i] = new_content
                        BREAK

            ELSE IF target_type is "frontmatter":
                IF lines[0] is "---":
                    end_idx = 1
                    WHILE end_idx < length AND lines[end_idx] != "---":
                        INCREMENT end_idx

                    IF operation is "append" OR "prepend":
                        INSERT "{target}: {new_content}" at end_idx
                    ELSE IF operation is "replace":
                        FOR i FROM 1 TO end_idx:
                            IF lines[i] starts with "{target}:":
                                SET lines[i] = "{target}: {new_content}"
                                BREAK

            WRITE JOIN(lines, newline) to file_path

        CATCH Exception:
            RAISE error

        RETURN success message
```

## Complex Search Tool

```
CLASS ComplexSearchToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_complex_search"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Complex search with glob/regex patterns"
            inputSchema = {query: object}

    FUNCTION run_tool(args):
        IF query not in args:
            RAISE error

        query = args.query
        results = empty list

        FOR EACH file_path IN vault_root.rglob("*"):
            IF file_path is not file OR name starts with '.':
                SKIP

            relative_path = CALCULATE file_path relative to vault_root

            TRY:
                content = READ file_path

                IF CALL _matches_query(query, relative_path, content):
                    APPEND relative_path to results

            CATCH UnicodeDecodeError OR PermissionError:
                SKIP

        RETURN JSON of results

    FUNCTION _matches_query(query, path, content):
        IF "and" in query:
            RETURN ALL of [_matches_query(q, path, content) FOR q IN query.and]
        ELSE IF "or" in query:
            RETURN ANY of [_matches_query(q, path, content) FOR q IN query.or]
        ELSE IF "glob" in query:
            pattern, target = query.glob
            value = path IF target is "path" ELSE content
            RETURN fnmatch(value, pattern)
        ELSE IF "regexp" in query:
            pattern, target = query.regexp
            value = path IF target is "path" ELSE content
            RETURN regex.search(pattern, value) is not null
        RETURN False
```

## Batch Get Files Tool

```
CLASS BatchGetFileContentsToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_batch_get_file_contents"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Return contents of multiple files"
            inputSchema = {filepaths: array of strings}

    FUNCTION run_tool(args):
        IF filepaths not in args:
            RAISE error

        result = empty list

        FOR EACH filepath IN args.filepaths:
            TRY:
                file_path = GET vault_path(filepath)
                content = READ file_path
                APPEND "# {filepath}\n\n{content}\n\n---\n\n" to result
            CATCH Exception as e:
                APPEND "# {filepath}\n\nError: {e}\n\n---\n\n" to result

        RETURN JOIN(result)
```

## Periodic Notes Tools

```
CLASS PeriodicNotesToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_get_periodic_note"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Get current periodic note"
            inputSchema = {period: enum, type: enum}

    FUNCTION run_tool(args):
        IF period not in args:
            RAISE error

        period = args.period
        type_arg = GET args.type OR "content"
        now = CURRENT datetime

        IF period is "daily":
            filename = FORMAT now as "YYYY-MM-DD.md"
        ELSE IF period is "weekly":
            filename = FORMAT now as "YYYY-Www.md"
        ELSE IF period is "monthly":
            filename = FORMAT now as "YYYY-MM.md"
        ELSE IF period is "quarterly":
            quarter = CALCULATE (now.month - 1) / 3 + 1
            filename = "YYYY-Qq.md"
        ELSE IF period is "yearly":
            filename = FORMAT now as "YYYY.md"
        ELSE:
            RAISE error

        search_paths = [
            filename,
            "Daily/{filename}",
            "Periodic/{filename}",
            "Journal/{filename}",
            "{period.capitalize()}/{filename}"
        ]

        FOR EACH search_path IN search_paths:
            TRY:
                file_path = GET vault_path(search_path)
                IF file_path exists:
                    content = READ file_path

                    IF type_arg is "metadata":
                        RETURN JSON {path, content, mtime}
                    ELSE:
                        RETURN content
            CATCH Exception:
                CONTINUE

        RAISE error "Periodic note not found"

CLASS RecentPeriodicNotesToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_get_recent_periodic_notes"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Get recent periodic notes"
            inputSchema = {period: enum, limit: int, include_content: bool}

    FUNCTION run_tool(args):
        IF period not in args:
            RAISE error

        period = args.period
        limit = GET args.limit OR 5
        include_content = GET args.include_content OR False

        patterns = {
            "daily": regex "\d{4}-\d{2}-\d{2}\.md",
            "weekly": regex "\d{4}-W\d{2}\.md",
            "monthly": regex "\d{4}-\d{2}\.md",
            "quarterly": regex "\d{4}-Q[1-4]\.md",
            "yearly": regex "\d{4}\.md"
        }

        pattern = GET patterns[period]
        IF pattern is null:
            RAISE error

        matching_files = empty list

        FOR EACH file_path IN vault_root.rglob("*.md"):
            IF REGEX MATCH pattern on file_path.name:
                APPEND file_path to matching_files

        SORT matching_files BY modification time DESCENDING
        matching_files = TAKE first limit items

        results = empty list
        FOR EACH file_path IN matching_files:
            relative_path = CALCULATE file_path relative to vault_root
            result = {path: relative_path, mtime: file_path.stat().mtime}

            IF include_content:
                TRY:
                    result.content = READ file_path
                CATCH Exception:
                    result.content = null

            APPEND result to results

        RETURN JSON of results
```

## Recent Changes Tool

```
CLASS RecentChangesToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_get_recent_changes"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Get recently modified files"
            inputSchema = {limit: int, days: int}

    FUNCTION run_tool(args):
        limit = GET args.limit OR 10
        days = GET args.days OR 90

        cutoff_time = CALCULATE (now - timedelta(days)).timestamp()
        recent_files = empty list

        FOR EACH file_path IN vault_root.rglob("*"):
            IF file_path is not file OR name starts with '.':
                SKIP

            mtime = GET file_path modification time
            IF mtime >= cutoff_time:
                APPEND {path: relative_path, mtime} to recent_files

        SORT recent_files BY mtime DESCENDING
        recent_files = TAKE first limit items

        RETURN JSON of recent_files
```

## Fuzzy Search Tool

```
CLASS FuzzySearchToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_fuzzy_search"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Fuzzy search for files by filename"
            inputSchema = {query: string, limit: int, score_threshold: number, search_content: bool}

    FUNCTION run_tool(args):
        IF query not in args:
            RAISE error

        query = args.query
        limit = GET args.limit OR 10
        score_threshold = GET args.score_threshold OR 60
        search_content = GET args.search_content OR False

        file_paths = empty list
        FOR EACH file_path IN vault_root.rglob("*"):
            IF file_path is file AND name does not start with '.':
                APPEND relative_path to file_paths

        results = empty list

        IF search_content:
            FOR EACH file_path_str IN file_paths:
                filename_score = FUZZY MATCH query TO file_path_str

                IF filename_score >= score_threshold:
                    APPEND {filepath, score: filename_score, match_type: "filename"} to results
                ELSE:
                    TRY:
                        file_path = GET vault_path(file_path_str)
                        content = READ file_path

                        IF content not empty:
                            content_score = FUZZY PARTIAL MATCH query TO content

                            IF content_score >= score_threshold:
                                APPEND {filepath, score: content_score, match_type: "content"} to results
                    CATCH Exception:
                        SKIP
        ELSE:
            matches = FUZZY PROCESS.EXTRACT(query, file_paths, limit * 2, score_threshold)

            results = [
                {filepath: match[0], score: match[1], match_type: "filename"}
                FOR match IN matches
            ]

        SORT results BY score DESCENDING
        results = TAKE first limit items

        RETURN JSON of results
```

## List Bases Tool

```
CLASS ListBasesToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_list_bases"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "List all .base files with their structure"
            inputSchema = empty object

    FUNCTION run_tool(args):
        base_files = empty list
        FOR EACH file_path IN vault_root.rglob("*.base"):
            IF name does not start with '.':
                APPEND file_path to base_files

        bases_info = empty list
        FOR EACH base_path IN base_files:
            TRY:
                content = READ base_path
                relative_path = CALCULATE base_path relative to vault_root

                IF content not empty:
                    base_config = PARSE YAML content

                    filter_properties = empty set
                    IF "filters" in base_config:
                        filter_str = STRING base_config.filters
                        property_matches = REGEX FINDALL r'[\w\.]+(?=\s*[=<>!])' IN filter_str
                        ADD property_matches to filter_properties

                    all_columns = empty set
                    views_info = empty list
                    IF "views" in base_config AND is list:
                        FOR EACH view IN base_config.views:
                            view_name = GET view.name OR "Unnamed"
                            view_type = GET view.type OR "table"
                            columns = GET view.order OR empty list
                            ADD columns to all_columns
                            APPEND {name, type, columns} to views_info

                    APPEND {filepath, name, filters, filter_properties, views, all_columns} to bases_info

            CATCH Exception as e:
                APPEND {filepath, name, error} to bases_info

        RETURN JSON of bases_info
```

## Search Bases Tool

```
CLASS SearchBasesToolHandler(ToolHandler):
    FUNCTION __init__():
        CALL parent __init__ with "obsidian_search_bases"

    FUNCTION get_tool_description():
        RETURN Tool schema with:
            name = self.name
            description = "Search notes within specific base"
            inputSchema = {base_name: string, property_filters: object, include_content: bool, limit: int}

    FUNCTION run_tool(args):
        IF base_name not in args:
            RAISE error

        base_name = args.base_name
        property_filters = GET args.property_filters OR empty dict
        include_content = GET args.include_content OR False
        limit = GET args.limit OR 50

        base_path = null
        FOR EACH file_path IN vault_root.rglob("{base_name}.base"):
            IF name does not start with '.':
                base_path = file_path
                BREAK

        IF base_path is null:
            RAISE error "Base not found"

        content = READ base_path
        IF content is empty:
            RAISE error

        base_config = PARSE YAML content

        target_folder = null
        IF "filters" in base_config:
            filters = base_config.filters
            IF filters is dict:
                and_conditions = GET filters.and OR empty list
                FOR EACH condition IN and_conditions:
                    IF condition is string AND "file.folder" in condition:
                        match = REGEX SEARCH r'file\.folder\s*==\s*["\']([^"\']+)["\']' IN condition
                        IF match:
                            target_folder = match.group(1)

        IF target_folder:
            search_path = GET vault_path(target_folder)
            IF search_path exists:
                md_files = LIST search_path.rglob("*.md")
            ELSE:
                md_files = empty list
        ELSE:
            md_files = LIST vault_root.rglob("*.md")

        results = empty list
        FOR EACH file_path IN FIRST limit * 2 OF md_files:
            IF file_path.name starts with '.':
                SKIP

            TRY:
                file_content = READ file_path

                properties = empty dict
                IF file_content starts with "---":
                    parts = SPLIT file_content BY "---" (max 3 parts)
                    IF length of parts >= 3:
                        frontmatter = parts[1]
                        TRY:
                            properties = PARSE YAML frontmatter OR empty dict
                        CATCH Exception:
                            properties = empty dict

                matches = True
                IF property_filters not empty:
                    FOR EACH prop_key, prop_value IN property_filters:
                        IF prop_key not in properties:
                            matches = False
                            BREAK

                        actual_value = properties[prop_key]
                        IF prop_value is string AND actual_value is string:
                            IF LOWERCASE prop_value not in LOWERCASE actual_value:
                                matches = False
                                BREAK
                        ELSE IF actual_value != prop_value:
                            matches = False
                            BREAK

                IF matches:
                    result = {filepath: relative_path, properties}

                    IF include_content:
                        IF file_content starts with "---":
                            parts = SPLIT file_content BY "---" (max 3 parts)
                            IF length of parts >= 3:
                                result.content = STRIP parts[2]
                        ELSE:
                            result.content = file_content

                    APPEND result to results

                    IF length of results >= limit:
                        BREAK

            CATCH Exception:
                SKIP

        RETURN JSON {base: base_name, total_results: count, results}
```

## MCP Server Setup

```
CREATE Server instance "mcp-obsidian"
CREATE tool_handlers empty dict

FUNCTION add_tool_handler(tool_class):
    SET tool_handlers[tool_class.name] = tool_class

FUNCTION get_tool_handler(name):
    IF name not in tool_handlers:
        RETURN null
    RETURN tool_handlers[name]

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

ASYNC FUNCTION list_tools():
    RETURN [th.get_tool_description() FOR th IN tool_handlers.values()]

ASYNC FUNCTION call_tool(name, arguments):
    IF arguments is not dict:
        RAISE error "Arguments must be dictionary"

    tool_handler = GET tool_handler(name)
    IF tool_handler is null:
        RAISE error "Unknown tool"

    TRY:
        RETURN CALL tool_handler.run_tool(arguments)
    CATCH Exception as e:
        LOG error
        RAISE error with exception message

ASYNC FUNCTION main():
    IMPORT stdio_server from mcp.server.stdio

    ASYNC WITH stdio_server() as (read_stream, write_stream):
        AWAIT app.run(read_stream, write_stream, initialization_options)
```

## Entry Point

```
IF module is main:
    CALL asyncio.run(main())
```
