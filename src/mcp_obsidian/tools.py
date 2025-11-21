from collections.abc import Sequence
from mcp.types import (
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
)
import json
import os
import yaml
import re
from rapidfuzz import fuzz, process
from . import obsidian

api_key = os.getenv("OBSIDIAN_API_KEY", "")
obsidian_host = os.getenv("OBSIDIAN_HOST", "127.0.0.1")

if api_key == "":
    raise ValueError(f"OBSIDIAN_API_KEY environment variable required. Working directory: {os.getcwd()}")

TOOL_LIST_FILES_IN_VAULT = "obsidian_list_files_in_vault"
TOOL_LIST_FILES_IN_DIR = "obsidian_list_files_in_dir"

class ToolHandler():
    def __init__(self, tool_name: str):
        self.name = tool_name

    def get_tool_description(self) -> Tool:
        raise NotImplementedError()

    def run_tool(self, args: dict) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
        raise NotImplementedError()
    
class ListFilesInVaultToolHandler(ToolHandler):
    def __init__(self):
        super().__init__(TOOL_LIST_FILES_IN_VAULT)

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="Lists all files and directories in the root directory of your Obsidian vault.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            },
        )

    def run_tool(self, args: dict) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
        api = obsidian.Obsidian(api_key=api_key, host=obsidian_host)

        files = api.list_files_in_vault()

        return [
            TextContent(
                type="text",
                text=json.dumps(files, indent=2)
            )
        ]
    
class ListFilesInDirToolHandler(ToolHandler):
    def __init__(self):
        super().__init__(TOOL_LIST_FILES_IN_DIR)

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="Lists all files and directories that exist in a specific Obsidian directory.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dirpath": {
                        "type": "string",
                        "description": "Path to list files from (relative to your vault root). Note that empty directories will not be returned."
                    },
                },
                "required": ["dirpath"]
            }
        )

    def run_tool(self, args: dict) -> Sequence[TextContent | ImageContent | EmbeddedResource]:

        if "dirpath" not in args:
            raise RuntimeError("dirpath argument missing in arguments")

        api = obsidian.Obsidian(api_key=api_key, host=obsidian_host)

        files = api.list_files_in_dir(args["dirpath"])

        return [
            TextContent(
                type="text",
                text=json.dumps(files, indent=2)
            )
        ]
    
class GetFileContentsToolHandler(ToolHandler):
    def __init__(self):
        super().__init__("obsidian_get_file_contents")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="Return the content of a single file in your vault.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Path to the relevant file (relative to your vault root).",
                        "format": "path"
                    },
                },
                "required": ["filepath"]
            }
        )

    def run_tool(self, args: dict) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
        if "filepath" not in args:
            raise RuntimeError("filepath argument missing in arguments")

        api = obsidian.Obsidian(api_key=api_key, host=obsidian_host)

        content = api.get_file_contents(args["filepath"])

        return [
            TextContent(
                type="text",
                text=json.dumps(content, indent=2)
            )
        ]
    
class SearchToolHandler(ToolHandler):
    def __init__(self):
        super().__init__("obsidian_simple_search")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="""Simple search for documents matching a specified text query across all files in the vault. 
            Use this tool when you want to do a simple text search""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text to a simple search for in the vault."
                    },
                    "context_length": {
                        "type": "integer",
                        "description": "How much context to return around the matching string (default: 100)",
                        "default": 100
                    }
                },
                "required": ["query"]
            }
        )

    def run_tool(self, args: dict) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
        if "query" not in args:
            raise RuntimeError("query argument missing in arguments")

        context_length = args.get("context_length", 100)
        
        api = obsidian.Obsidian(api_key=api_key, host=obsidian_host)
        results = api.search(args["query"], context_length)
        
        formatted_results = []
        for result in results:
            formatted_matches = []
            for match in result.get('matches', []):
                context = match.get('context', '')
                match_pos = match.get('match', {})
                start = match_pos.get('start', 0)
                end = match_pos.get('end', 0)
                
                formatted_matches.append({
                    'context': context,
                    'match_position': {'start': start, 'end': end}
                })
                
            formatted_results.append({
                'filename': result.get('filename', ''),
                'score': result.get('score', 0),
                'matches': formatted_matches
            })

        return [
            TextContent(
                type="text",
                text=json.dumps(formatted_results, indent=2)
            )
        ]
    
class AppendContentToolHandler(ToolHandler):
   def __init__(self):
       super().__init__("obsidian_append_content")

   def get_tool_description(self):
       return Tool(
           name=self.name,
           description="Append content to a new or existing file in the vault.",
           inputSchema={
               "type": "object",
               "properties": {
                   "filepath": {
                       "type": "string",
                       "description": "Path to the file (relative to vault root)",
                       "format": "path"
                   },
                   "content": {
                       "type": "string",
                       "description": "Content to append to the file"
                   }
               },
               "required": ["filepath", "content"]
           }
       )

   def run_tool(self, args: dict) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
       if "filepath" not in args or "content" not in args:
           raise RuntimeError("filepath and content arguments required")

       api = obsidian.Obsidian(api_key=api_key, host=obsidian_host)
       api.append_content(args.get("filepath", ""), args["content"])

       return [
           TextContent(
               type="text",
               text=f"Successfully appended content to {args['filepath']}"
           )
       ]
   
class PatchContentToolHandler(ToolHandler):
   def __init__(self):
       super().__init__("obsidian_patch_content")

   def get_tool_description(self):
       return Tool(
           name=self.name,
           description="Insert content into an existing note relative to a heading, block reference, or frontmatter field.",
           inputSchema={
               "type": "object",
               "properties": {
                   "filepath": {
                       "type": "string",
                       "description": "Path to the file (relative to vault root)",
                       "format": "path"
                   },
                   "operation": {
                       "type": "string",
                       "description": "Operation to perform (append, prepend, or replace)",
                       "enum": ["append", "prepend", "replace"]
                   },
                   "target_type": {
                       "type": "string",
                       "description": "Type of target to patch",
                       "enum": ["heading", "block", "frontmatter"]
                   },
                   "target": {
                       "type": "string", 
                       "description": "Target identifier (heading path, block reference, or frontmatter field)"
                   },
                   "content": {
                       "type": "string",
                       "description": "Content to insert"
                   }
               },
               "required": ["filepath", "operation", "target_type", "target", "content"]
           }
       )

   def run_tool(self, args: dict) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
       if not all(k in args for k in ["filepath", "operation", "target_type", "target", "content"]):
           raise RuntimeError("filepath, operation, target_type, target and content arguments required")

       api = obsidian.Obsidian(api_key=api_key, host=obsidian_host)
       api.patch_content(
           args.get("filepath", ""),
           args.get("operation", ""),
           args.get("target_type", ""),
           args.get("target", ""),
           args.get("content", "")
       )

       return [
           TextContent(
               type="text",
               text=f"Successfully patched content in {args['filepath']}"
           )
       ]
       
class PutContentToolHandler(ToolHandler):
   def __init__(self):
       super().__init__("obsidian_put_content")

   def get_tool_description(self):
       return Tool(
           name=self.name,
           description="Create a new file in your vault or update the content of an existing one in your vault.",
           inputSchema={
               "type": "object",
               "properties": {
                   "filepath": {
                       "type": "string",
                       "description": "Path to the relevant file (relative to your vault root)",
                       "format": "path"
                   },
                   "content": {
                       "type": "string",
                       "description": "Content of the file you would like to upload"
                   }
               },
               "required": ["filepath", "content"]
           }
       )

   def run_tool(self, args: dict) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
       if "filepath" not in args or "content" not in args:
           raise RuntimeError("filepath and content arguments required")

       api = obsidian.Obsidian(api_key=api_key, host=obsidian_host)
       api.put_content(args.get("filepath", ""), args["content"])

       return [
           TextContent(
               type="text",
               text=f"Successfully uploaded content to {args['filepath']}"
           )
       ]
   

class DeleteFileToolHandler(ToolHandler):
   def __init__(self):
       super().__init__("obsidian_delete_file")

   def get_tool_description(self):
       return Tool(
           name=self.name,
           description="Delete a file or directory from the vault.",
           inputSchema={
               "type": "object",
               "properties": {
                   "filepath": {
                       "type": "string",
                       "description": "Path to the file or directory to delete (relative to vault root)",
                       "format": "path"
                   },
                   "confirm": {
                       "type": "boolean",
                       "description": "Confirmation to delete the file (must be true)",
                       "default": False
                   }
               },
               "required": ["filepath", "confirm"]
           }
       )

   def run_tool(self, args: dict) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
       if "filepath" not in args:
           raise RuntimeError("filepath argument missing in arguments")
       
       if not args.get("confirm", False):
           raise RuntimeError("confirm must be set to true to delete a file")

       api = obsidian.Obsidian(api_key=api_key, host=obsidian_host)
       api.delete_file(args["filepath"])

       return [
           TextContent(
               type="text",
               text=f"Successfully deleted {args['filepath']}"
           )
       ]
   
class ComplexSearchToolHandler(ToolHandler):
   def __init__(self):
       super().__init__("obsidian_complex_search")

   def get_tool_description(self):
       return Tool(
           name=self.name,
           description="""Complex search for documents using a JsonLogic query. 
           Supports standard JsonLogic operators plus 'glob' and 'regexp' for pattern matching. Results must be non-falsy.

           Use this tool when you want to do a complex search, e.g. for all documents with certain tags etc.
           ALWAYS follow query syntax in examples.

           Examples
            1. Match all markdown files
            {"glob": ["*.md", {"var": "path"}]}

            2. Match all markdown files with 1221 substring inside them
            {
              "and": [
                { "glob": ["*.md", {"var": "path"}] },
                { "regexp": [".*1221.*", {"var": "content"}] }
              ]
            }

            3. Match all markdown files in Work folder containing name Keaton
            {
              "and": [
                { "glob": ["*.md", {"var": "path"}] },
                { "regexp": [".*Work.*", {"var": "path"}] },
                { "regexp": ["Keaton", {"var": "content"}] }
              ]
            }
           """,
           inputSchema={
               "type": "object",
               "properties": {
                   "query": {
                       "type": "object",
                       "description": "JsonLogic query object. ALWAYS follow query syntax in examples. \
                            Example 1: {\"glob\": [\"*.md\", {\"var\": \"path\"}]} matches all markdown files \
                            Example 2: {\"and\": [{\"glob\": [\"*.md\", {\"var\": \"path\"}]}, {\"regexp\": [\".*1221.*\", {\"var\": \"content\"}]}]} matches all markdown files with 1221 substring inside them \
                            Example 3: {\"and\": [{\"glob\": [\"*.md\", {\"var\": \"path\"}]}, {\"regexp\": [\".*Work.*\", {\"var\": \"path\"}]}, {\"regexp\": [\"Keaton\", {\"var\": \"content\"}]}]} matches all markdown files in Work folder containing name Keaton \
                        "
                   }
               },
               "required": ["query"]
           }
       )

   def run_tool(self, args: dict) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
       if "query" not in args:
           raise RuntimeError("query argument missing in arguments")

       api = obsidian.Obsidian(api_key=api_key, host=obsidian_host)
       results = api.search_json(args.get("query", ""))

       return [
           TextContent(
               type="text",
               text=json.dumps(results, indent=2)
           )
       ]

class BatchGetFileContentsToolHandler(ToolHandler):
    def __init__(self):
        super().__init__("obsidian_batch_get_file_contents")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="Return the contents of multiple files in your vault, concatenated with headers.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepaths": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "description": "Path to a file (relative to your vault root)",
                            "format": "path"
                        },
                        "description": "List of file paths to read"
                    },
                },
                "required": ["filepaths"]
            }
        )

    def run_tool(self, args: dict) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
        if "filepaths" not in args:
            raise RuntimeError("filepaths argument missing in arguments")

        api = obsidian.Obsidian(api_key=api_key, host=obsidian_host)
        content = api.get_batch_file_contents(args["filepaths"])

        return [
            TextContent(
                type="text",
                text=content
            )
        ]

class PeriodicNotesToolHandler(ToolHandler):
    def __init__(self):
        super().__init__("obsidian_get_periodic_note")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="Get current periodic note for the specified period.",
            inputSchema={
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "description": "The period type (daily, weekly, monthly, quarterly, yearly)",
                        "enum": ["daily", "weekly", "monthly", "quarterly", "yearly"]
                    },
                    "type": {
                        "type": "string",
                        "description": "The type of data to get ('content' or 'metadata'). 'content' returns just the content in Markdown format. 'metadata' includes note metadata (including paths, tags, etc.) and the content.",
                        "default": "content",
                        "enum": ["content", "metadata"]
                    }
                },
                "required": ["period"]
            }
        )

    def run_tool(self, args: dict) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
        if "period" not in args:
            raise RuntimeError("period argument missing in arguments")

        period = args["period"]
        valid_periods = ["daily", "weekly", "monthly", "quarterly", "yearly"]
        if period not in valid_periods:
            raise RuntimeError(f"Invalid period: {period}. Must be one of: {', '.join(valid_periods)}")
        
        type = args["type"] if "type" in args else "content"
        valid_types = ["content", "metadata"]
        if type not in valid_types:
            raise RuntimeError(f"Invalid type: {type}. Must be one of: {', '.join(valid_types)}")

        api = obsidian.Obsidian(api_key=api_key, host=obsidian_host)
        content = api.get_periodic_note(period,type)

        return [
            TextContent(
                type="text",
                text=content
            )
        ]
        
class RecentPeriodicNotesToolHandler(ToolHandler):
    def __init__(self):
        super().__init__("obsidian_get_recent_periodic_notes")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="Get most recent periodic notes for the specified period type.",
            inputSchema={
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "description": "The period type (daily, weekly, monthly, quarterly, yearly)",
                        "enum": ["daily", "weekly", "monthly", "quarterly", "yearly"]
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of notes to return (default: 5)",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 50
                    },
                    "include_content": {
                        "type": "boolean",
                        "description": "Whether to include note content (default: false)",
                        "default": False
                    }
                },
                "required": ["period"]
            }
        )

    def run_tool(self, args: dict) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
        if "period" not in args:
            raise RuntimeError("period argument missing in arguments")

        period = args["period"]
        valid_periods = ["daily", "weekly", "monthly", "quarterly", "yearly"]
        if period not in valid_periods:
            raise RuntimeError(f"Invalid period: {period}. Must be one of: {', '.join(valid_periods)}")

        limit = args.get("limit", 5)
        if not isinstance(limit, int) or limit < 1:
            raise RuntimeError(f"Invalid limit: {limit}. Must be a positive integer")
            
        include_content = args.get("include_content", False)
        if not isinstance(include_content, bool):
            raise RuntimeError(f"Invalid include_content: {include_content}. Must be a boolean")

        api = obsidian.Obsidian(api_key=api_key, host=obsidian_host)
        results = api.get_recent_periodic_notes(period, limit, include_content)

        return [
            TextContent(
                type="text",
                text=json.dumps(results, indent=2)
            )
        ]
        
class RecentChangesToolHandler(ToolHandler):
    def __init__(self):
        super().__init__("obsidian_get_recent_changes")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="Get recently modified files in the vault.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of files to return (default: 10)",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 100
                    },
                    "days": {
                        "type": "integer",
                        "description": "Only include files modified within this many days (default: 90)",
                        "minimum": 1,
                        "default": 90
                    }
                }
            }
        )

    def run_tool(self, args: dict) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
        limit = args.get("limit", 10)
        if not isinstance(limit, int) or limit < 1:
            raise RuntimeError(f"Invalid limit: {limit}. Must be a positive integer")
            
        days = args.get("days", 90)
        if not isinstance(days, int) or days < 1:
            raise RuntimeError(f"Invalid days: {days}. Must be a positive integer")

        api = obsidian.Obsidian(api_key=api_key, host=obsidian_host)
        results = api.get_recent_changes(limit, days)

        return [
            TextContent(
                type="text",
                text=json.dumps(results, indent=2)
            )
        ]

class FuzzySearchToolHandler(ToolHandler):
    def __init__(self):
        super().__init__("obsidian_fuzzy_search")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="""Fuzzy search for files in the vault by filename using fuzzy string matching.
            This is useful when you're not sure of the exact filename or want to find files with similar names.
            The search is case-insensitive and tolerant of typos and partial matches.

            Use this tool when you want to find files even if you don't know the exact name, or when dealing with typos.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text to fuzzy search for in filenames"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 10)",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 50
                    },
                    "score_threshold": {
                        "type": "number",
                        "description": "Minimum similarity score (0-100) to include in results (default: 60)",
                        "default": 60,
                        "minimum": 0,
                        "maximum": 100
                    },
                    "search_content": {
                        "type": "boolean",
                        "description": "Whether to also fuzzy search file contents (default: false). Warning: searching content is slower.",
                        "default": False
                    }
                },
                "required": ["query"]
            }
        )

    def run_tool(self, args: dict) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
        if "query" not in args:
            raise RuntimeError("query argument missing in arguments")

        query = args["query"]
        limit = args.get("limit", 10)
        score_threshold = args.get("score_threshold", 60)
        search_content = args.get("search_content", False)

        api = obsidian.Obsidian(api_key=api_key, host=obsidian_host)

        # Get all files in the vault
        all_files = api.list_files_in_vault()

        # Extract file paths
        file_paths = []

        def extract_paths(items, prefix=""):
            for item in items:
                if isinstance(item, dict):
                    # It's a directory
                    for key, value in item.items():
                        new_prefix = f"{prefix}{key}/" if prefix else f"{key}/"
                        extract_paths(value, new_prefix)
                elif isinstance(item, str):
                    # It's a file
                    file_paths.append(f"{prefix}{item}")

        extract_paths(all_files)

        # Perform fuzzy matching on filenames
        results = []

        if search_content:
            # Search both filename and content (slower)
            for file_path in file_paths:
                # Score based on filename
                filename_score = fuzz.WRatio(query.lower(), file_path.lower())

                # If filename score is high enough, include it
                if filename_score >= score_threshold:
                    results.append({
                        'filepath': file_path,
                        'score': filename_score,
                        'match_type': 'filename'
                    })
                else:
                    # Try content search for files that didn't match by name
                    try:
                        content_data = api.get_file_contents(file_path)
                        content = content_data.get('content', '') if isinstance(content_data, dict) else ''

                        if content:
                            # Use partial ratio for content matching
                            content_score = fuzz.partial_ratio(query.lower(), content.lower())

                            if content_score >= score_threshold:
                                results.append({
                                    'filepath': file_path,
                                    'score': content_score,
                                    'match_type': 'content'
                                })
                    except Exception:
                        # Skip files that can't be read
                        pass
        else:
            # Search filenames only (faster)
            # Use process.extract for efficient batch processing
            matches = process.extract(
                query,
                file_paths,
                scorer=fuzz.WRatio,
                limit=limit * 2,  # Get more matches than needed to filter by threshold
                score_cutoff=score_threshold
            )

            results = [
                {
                    'filepath': match[0],
                    'score': match[1],
                    'match_type': 'filename'
                }
                for match in matches
            ]

        # Sort by score descending and limit results
        results.sort(key=lambda x: x['score'], reverse=True)
        results = results[:limit]

        return [
            TextContent(
                type="text",
                text=json.dumps(results, indent=2)
            )
        ]

class ListBasesToolHandler(ToolHandler):
    def __init__(self):
        super().__init__("obsidian_list_bases")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="""List all Obsidian Bases (.base files) in the vault with their structure.
            Returns information about each base including its filters, views, and available properties/columns.
            This is useful for discovering what bases exist and what properties can be searched.""",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        )

    def run_tool(self, args: dict) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
        api = obsidian.Obsidian(api_key=api_key, host=obsidian_host)

        # Get all files in the vault
        all_files = api.list_files_in_vault()

        # Extract file paths and find .base files
        base_files = []

        def extract_paths(items, prefix=""):
            for item in items:
                if isinstance(item, dict):
                    # It's a directory
                    for key, value in item.items():
                        new_prefix = f"{prefix}{key}/" if prefix else f"{key}/"
                        extract_paths(value, new_prefix)
                elif isinstance(item, str):
                    # It's a file - check if it's a .base file
                    if item.endswith('.base'):
                        base_files.append(f"{prefix}{item}")

        extract_paths(all_files)

        # Parse each base file
        bases_info = []
        for base_path in base_files:
            try:
                # Get the content of the base file
                content_data = api.get_file_contents(base_path)
                content = content_data.get('content', '') if isinstance(content_data, dict) else ''

                if content:
                    # Parse YAML
                    base_config = yaml.safe_load(content)

                    # Extract filter properties
                    filter_properties = set()
                    if 'filters' in base_config:
                        filter_str = str(base_config['filters'])
                        # Extract property names from filter expressions
                        # Look for patterns like "file.folder", "tags", "type", "status", etc.
                        property_matches = re.findall(r'[\w\.]+(?=\s*[=<>!])', filter_str)
                        filter_properties.update(property_matches)

                    # Extract view columns
                    all_columns = set()
                    views_info = []
                    if 'views' in base_config and isinstance(base_config['views'], list):
                        for view in base_config['views']:
                            view_name = view.get('name', 'Unnamed')
                            view_type = view.get('type', 'table')
                            columns = view.get('order', [])
                            all_columns.update(columns)
                            views_info.append({
                                'name': view_name,
                                'type': view_type,
                                'columns': columns
                            })

                    bases_info.append({
                        'filepath': base_path,
                        'name': base_path.split('/')[-1].replace('.base', ''),
                        'filters': base_config.get('filters', {}),
                        'filter_properties': sorted(list(filter_properties)),
                        'views': views_info,
                        'all_columns': sorted(list(all_columns))
                    })

            except Exception as e:
                # If we can't parse a base, include it with error info
                bases_info.append({
                    'filepath': base_path,
                    'name': base_path.split('/')[-1].replace('.base', ''),
                    'error': f"Failed to parse: {str(e)}"
                })

        return [
            TextContent(
                type="text",
                text=json.dumps(bases_info, indent=2)
            )
        ]

class SearchBasesToolHandler(ToolHandler):
    def __init__(self):
        super().__init__("obsidian_search_bases")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="""Search for notes within a specific Obsidian Base by filtering on properties.
            First use obsidian_list_bases to discover available bases and their properties.

            This tool finds notes that match the base's filter criteria and optionally applies
            additional property filters. Results include note paths and their property values.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "base_name": {
                        "type": "string",
                        "description": "Name of the base to search (without .base extension)"
                    },
                    "property_filters": {
                        "type": "object",
                        "description": "Optional property filters as key-value pairs. Supports exact matches and partial text matching.",
                        "additionalProperties": True
                    },
                    "include_content": {
                        "type": "boolean",
                        "description": "Whether to include full note content in results (default: false)",
                        "default": False
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 50)",
                        "default": 50,
                        "minimum": 1,
                        "maximum": 200
                    }
                },
                "required": ["base_name"]
            }
        )

    def run_tool(self, args: dict) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
        if "base_name" not in args:
            raise RuntimeError("base_name argument missing in arguments")

        base_name = args["base_name"]
        property_filters = args.get("property_filters", {})
        include_content = args.get("include_content", False)
        limit = args.get("limit", 50)

        api = obsidian.Obsidian(api_key=api_key, host=obsidian_host)

        # Find the base file
        all_files = api.list_files_in_vault()
        base_path = None

        def find_base(items, prefix=""):
            nonlocal base_path
            for item in items:
                if isinstance(item, dict):
                    for key, value in item.items():
                        new_prefix = f"{prefix}{key}/" if prefix else f"{key}/"
                        find_base(value, new_prefix)
                elif isinstance(item, str):
                    if item == f"{base_name}.base" or item.endswith(f"/{base_name}.base"):
                        base_path = f"{prefix}{item}"
                        return

        find_base(all_files)

        if not base_path:
            raise RuntimeError(f"Base '{base_name}' not found in vault")

        # Load and parse the base file
        content_data = api.get_file_contents(base_path)
        content = content_data.get('content', '') if isinstance(content_data, dict) else ''

        if not content:
            raise RuntimeError(f"Base file '{base_path}' is empty")

        base_config = yaml.safe_load(content)

        # Extract folder filter from base
        target_folder = None
        if 'filters' in base_config:
            filters = base_config.get('filters', {})
            # Look for file.folder filter
            if isinstance(filters, dict):
                and_conditions = filters.get('and', [])
                for condition in and_conditions:
                    if isinstance(condition, str) and 'file.folder' in condition:
                        # Extract folder path from condition like "file.folder == 'Files/Places'"
                        match = re.search(r'file\.folder\s*==\s*["\']([^"\']+)["\']', condition)
                        if match:
                            target_folder = match.group(1)

        # Get files from the target folder
        if target_folder:
            try:
                folder_files = api.list_files_in_dir(target_folder)
            except Exception:
                folder_files = []
        else:
            # If no folder filter, search entire vault
            folder_files = all_files

        # Extract markdown files
        md_files = []

        def extract_md_files(items, prefix=""):
            for item in items:
                if isinstance(item, dict):
                    for key, value in item.items():
                        new_prefix = f"{prefix}{key}/" if prefix else f"{key}/"
                        extract_md_files(value, new_prefix)
                elif isinstance(item, str):
                    if item.endswith('.md'):
                        full_path = f"{target_folder}/{prefix}{item}" if target_folder else f"{prefix}{item}"
                        md_files.append(full_path)

        extract_md_files(folder_files)

        # Filter files based on properties
        results = []
        for file_path in md_files[:limit * 2]:  # Get more than needed for filtering
            try:
                # Get file content to extract properties
                file_data = api.get_file_contents(file_path)
                file_content = file_data.get('content', '') if isinstance(file_data, dict) else ''

                # Parse frontmatter properties
                properties = {}
                if file_content.startswith('---'):
                    # Extract YAML frontmatter
                    parts = file_content.split('---', 2)
                    if len(parts) >= 3:
                        frontmatter = parts[1]
                        try:
                            properties = yaml.safe_load(frontmatter) or {}
                        except Exception:
                            properties = {}

                # Apply property filters
                matches = True
                if property_filters:
                    for prop_key, prop_value in property_filters.items():
                        if prop_key not in properties:
                            matches = False
                            break

                        actual_value = properties[prop_key]
                        # Support exact match or partial text match
                        if isinstance(prop_value, str) and isinstance(actual_value, str):
                            if prop_value.lower() not in str(actual_value).lower():
                                matches = False
                                break
                        elif actual_value != prop_value:
                            matches = False
                            break

                if matches:
                    result = {
                        'filepath': file_path,
                        'properties': properties
                    }

                    if include_content:
                        # Remove frontmatter from content
                        if file_content.startswith('---'):
                            parts = file_content.split('---', 2)
                            if len(parts) >= 3:
                                result['content'] = parts[2].strip()
                        else:
                            result['content'] = file_content

                    results.append(result)

                    if len(results) >= limit:
                        break

            except Exception:
                # Skip files that can't be read
                continue

        return [
            TextContent(
                type="text",
                text=json.dumps({
                    'base': base_name,
                    'total_results': len(results),
                    'results': results
                }, indent=2)
            )
        ]
