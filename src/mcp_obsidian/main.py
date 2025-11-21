"""
MCP Obsidian Server - Direct Filesystem Access
Consolidated single-file implementation
"""

import json
import logging
import os
import re
import shutil
import yaml
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server import Server
from mcp.types import (
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
)
from rapidfuzz import fuzz, process

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-obsidian")

# =============================================================================
# VAULT CONFIGURATION
# =============================================================================

vault_path = os.getenv("VAULT_PATH", "")

if vault_path == "":
    raise ValueError(f"VAULT_PATH environment variable required. Working directory: {os.getcwd()}")

vault_root = Path(vault_path).resolve()

if not vault_root.exists():
    raise ValueError(f"VAULT_PATH does not exist: {vault_path}")

if not vault_root.is_dir():
    raise ValueError(f"VAULT_PATH is not a directory: {vault_path}")

# Tool name constants
TOOL_LIST_FILES_IN_VAULT = "obsidian_list_files_in_vault"
TOOL_LIST_FILES_IN_DIR = "obsidian_list_files_in_dir"

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_vault_path(relative_path: str = "") -> Path:
    """Convert a relative vault path to absolute path and ensure it's within vault."""
    if relative_path:
        full_path = (vault_root / relative_path).resolve()
    else:
        full_path = vault_root.resolve()

    # Security check: ensure path is within vault
    try:
        full_path.relative_to(vault_root)
    except ValueError:
        raise RuntimeError(f"Path {relative_path} is outside vault")

    return full_path

def list_vault_files(dirpath: str = "") -> list:
    """Recursively list files in a directory, returning nested dict/list structure."""
    target_path = get_vault_path(dirpath)

    if not target_path.exists():
        raise RuntimeError(f"Directory does not exist: {dirpath}")

    if not target_path.is_dir():
        raise RuntimeError(f"Path is not a directory: {dirpath}")

    result = []

    try:
        items = sorted(target_path.iterdir(), key=lambda x: (not x.is_dir(), x.name))

        for item in items:
            # Skip hidden files and directories
            if item.name.startswith('.'):
                continue

            if item.is_dir():
                # Recursively get directory contents
                subdir_contents = list_vault_files(str(item.relative_to(vault_root)))
                if subdir_contents:  # Only include non-empty directories
                    result.append({item.name: subdir_contents})
            else:
                result.append(item.name)

    except PermissionError:
        raise RuntimeError(f"Permission denied accessing: {dirpath}")

    return result

# =============================================================================
# TOOL HANDLERS
# =============================================================================

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
        files = list_vault_files()

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

        files = list_vault_files(args["dirpath"])

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

        file_path = get_vault_path(args["filepath"])

        if not file_path.exists():
            raise RuntimeError(f"File does not exist: {args['filepath']}")

        if not file_path.is_file():
            raise RuntimeError(f"Path is not a file: {args['filepath']}")

        try:
            content = file_path.read_text(encoding='utf-8')
        except Exception as e:
            raise RuntimeError(f"Error reading file: {str(e)}")

        return [
            TextContent(
                type="text",
                text=content
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

        query = args["query"]
        context_length = args.get("context_length", 100)

        results = []

        # Search all files in vault
        for file_path in vault_root.rglob("*"):
            if not file_path.is_file() or file_path.name.startswith('.'):
                continue

            try:
                content = file_path.read_text(encoding='utf-8')
                relative_path = str(file_path.relative_to(vault_root))

                # Find all occurrences of query
                matches = []
                content_lower = content.lower()
                query_lower = query.lower()

                pos = 0
                while True:
                    pos = content_lower.find(query_lower, pos)
                    if pos == -1:
                        break

                    # Extract context
                    start = max(0, pos - context_length)
                    end = min(len(content), pos + len(query) + context_length)
                    context = content[start:end]

                    matches.append({
                        'context': context,
                        'match_position': {
                            'start': pos,
                            'end': pos + len(query)
                        }
                    })

                    pos += 1

                if matches:
                    results.append({
                        'filename': relative_path,
                        'score': len(matches),
                        'matches': matches
                    })

            except (UnicodeDecodeError, PermissionError):
                # Skip binary files or files we can't read
                continue

        return [
            TextContent(
                type="text",
                text=json.dumps(results, indent=2)
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

       file_path = get_vault_path(args["filepath"])

       # Create parent directories if they don't exist
       file_path.parent.mkdir(parents=True, exist_ok=True)

       try:
           with open(file_path, 'a', encoding='utf-8') as f:
               f.write(args["content"])
       except Exception as e:
           raise RuntimeError(f"Error appending to file: {str(e)}")

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

       file_path = get_vault_path(args["filepath"])

       if not file_path.exists() or not file_path.is_file():
           raise RuntimeError(f"File does not exist: {args['filepath']}")

       try:
           content = file_path.read_text(encoding='utf-8')
           lines = content.split('\n')

           operation = args["operation"]
           target_type = args["target_type"]
           target = args["target"]
           new_content = args["content"]

           if target_type == "heading":
               # Find the heading
               target_level = target.count('#')
               target_text = target.lstrip('#').strip()

               for i, line in enumerate(lines):
                   if line.startswith('#') and target_text.lower() in line.lower():
                       if operation == "prepend":
                           lines.insert(i + 1, new_content)
                       elif operation == "append":
                           # Find end of section (next heading of same or higher level)
                           j = i + 1
                           while j < len(lines):
                               if lines[j].startswith('#'):
                                   heading_level = len(lines[j]) - len(lines[j].lstrip('#'))
                                   if heading_level <= target_level:
                                       break
                               j += 1
                           lines.insert(j, new_content)
                       elif operation == "replace":
                           lines[i] = new_content
                       break

           elif target_type == "frontmatter":
               # Handle frontmatter modification
               if lines[0] == '---':
                   end_idx = 1
                   while end_idx < len(lines) and lines[end_idx] != '---':
                       end_idx += 1

                   if operation == "append" or operation == "prepend":
                       lines.insert(end_idx, f"{target}: {new_content}")
                   elif operation == "replace":
                       for i in range(1, end_idx):
                           if lines[i].startswith(f"{target}:"):
                               lines[i] = f"{target}: {new_content}"
                               break

           file_path.write_text('\n'.join(lines), encoding='utf-8')

       except Exception as e:
           raise RuntimeError(f"Error patching file: {str(e)}")

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

       file_path = get_vault_path(args["filepath"])

       # Create parent directories if they don't exist
       file_path.parent.mkdir(parents=True, exist_ok=True)

       try:
           file_path.write_text(args["content"], encoding='utf-8')
       except Exception as e:
           raise RuntimeError(f"Error writing file: {str(e)}")

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

       file_path = get_vault_path(args["filepath"])

       if not file_path.exists():
           raise RuntimeError(f"File does not exist: {args['filepath']}")

       try:
           if file_path.is_dir():
               shutil.rmtree(file_path)
           else:
               file_path.unlink()
       except Exception as e:
           raise RuntimeError(f"Error deleting file: {str(e)}")

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
           description="""Complex search for documents using glob and regex patterns.
           Supports pattern matching for filenames and content.

           Use this tool when you want to do a complex search, e.g. for all documents with certain tags etc.
           ALWAYS follow query syntax in examples.

           Examples
            1. Match all markdown files
            {"glob": ["*.md", "path"]}

            2. Match all markdown files with 1221 substring inside them
            {
              "and": [
                { "glob": ["*.md", "path"] },
                { "regexp": [".*1221.*", "content"] }
              ]
            }

            3. Match all markdown files in Work folder containing name Keaton
            {
              "and": [
                { "glob": ["*.md", "path"] },
                { "regexp": [".*Work.*", "path"] },
                { "regexp": ["Keaton", "content"] }
              ]
            }
           """,
           inputSchema={
               "type": "object",
               "properties": {
                   "query": {
                       "type": "object",
                       "description": "Query object with glob/regexp operators. \
                            Example 1: {\"glob\": [\"*.md\", \"path\"]} matches all markdown files \
                            Example 2: {\"and\": [{\"glob\": [\"*.md\", \"path\"]}, {\"regexp\": [\".*1221.*\", \"content\"]}]} matches all markdown files with 1221 substring inside them \
                            Example 3: {\"and\": [{\"glob\": [\"*.md\", \"path\"]}, {\"regexp\": [\".*Work.*\", \"path\"]}, {\"regexp\": [\"Keaton\", \"content\"]}]} matches all markdown files in Work folder containing name Keaton \
                        "
                   }
               },
               "required": ["query"]
           }
       )

   def run_tool(self, args: dict) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
       if "query" not in args:
           raise RuntimeError("query argument missing in arguments")

       query = args["query"]
       results = []

       # Process query and search files
       for file_path in vault_root.rglob("*"):
           if not file_path.is_file() or file_path.name.startswith('.'):
               continue

           relative_path = str(file_path.relative_to(vault_root))

           try:
               content = file_path.read_text(encoding='utf-8')

               # Simple query evaluation
               if self._matches_query(query, relative_path, content):
                   results.append(relative_path)

           except (UnicodeDecodeError, PermissionError):
               continue

       return [
           TextContent(
               type="text",
               text=json.dumps(results, indent=2)
           )
       ]

   def _matches_query(self, query: dict, path: str, content: str) -> bool:
       """Evaluate a query against a file."""
       if "and" in query:
           return all(self._matches_query(q, path, content) for q in query["and"])
       elif "or" in query:
           return any(self._matches_query(q, path, content) for q in query["or"])
       elif "glob" in query:
           pattern, target = query["glob"]
           value = path if target == "path" else content
           from fnmatch import fnmatch
           return fnmatch(value, pattern)
       elif "regexp" in query:
           pattern, target = query["regexp"]
           value = path if target == "path" else content
           return bool(re.search(pattern, value))
       return False

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

        result = []

        for filepath in args["filepaths"]:
            try:
                file_path = get_vault_path(filepath)
                content = file_path.read_text(encoding='utf-8')
                result.append(f"# {filepath}\n\n{content}\n\n---\n\n")
            except Exception as e:
                result.append(f"# {filepath}\n\nError reading file: {str(e)}\n\n---\n\n")

        return [
            TextContent(
                type="text",
                text="".join(result)
            )
        ]

class PeriodicNotesToolHandler(ToolHandler):
    def __init__(self):
        super().__init__("obsidian_get_periodic_note")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="Get current periodic note for the specified period. Note: This is a simplified implementation that looks for common periodic note patterns.",
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
        type_arg = args.get("type", "content")

        # Generate expected filename based on period
        now = datetime.now()
        if period == "daily":
            filename = now.strftime("%Y-%m-%d.md")
        elif period == "weekly":
            filename = now.strftime("%Y-W%W.md")
        elif period == "monthly":
            filename = now.strftime("%Y-%m.md")
        elif period == "quarterly":
            quarter = (now.month - 1) // 3 + 1
            filename = f"{now.year}-Q{quarter}.md"
        elif period == "yearly":
            filename = now.strftime("%Y.md")
        else:
            raise RuntimeError(f"Invalid period: {period}")

        # Search for the file in common periodic notes locations
        search_paths = [
            filename,
            f"Daily/{filename}",
            f"Periodic/{filename}",
            f"Journal/{filename}",
            f"{period.capitalize()}/{filename}"
        ]

        for search_path in search_paths:
            try:
                file_path = get_vault_path(search_path)
                if file_path.exists():
                    content = file_path.read_text(encoding='utf-8')

                    if type_arg == "metadata":
                        # Return with metadata
                        return [
                            TextContent(
                                type="text",
                                text=json.dumps({
                                    "path": search_path,
                                    "content": content,
                                    "mtime": file_path.stat().st_mtime
                                }, indent=2)
                            )
                        ]
                    else:
                        # Return just content
                        return [
                            TextContent(
                                type="text",
                                text=content
                            )
                        ]
            except Exception:
                continue

        raise RuntimeError(f"Periodic note not found for period: {period}")

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
        limit = args.get("limit", 5)
        include_content = args.get("include_content", False)

        # Search for periodic notes based on pattern
        patterns = {
            "daily": r"\d{4}-\d{2}-\d{2}\.md",
            "weekly": r"\d{4}-W\d{2}\.md",
            "monthly": r"\d{4}-\d{2}\.md",
            "quarterly": r"\d{4}-Q[1-4]\.md",
            "yearly": r"\d{4}\.md"
        }

        pattern = patterns.get(period)
        if not pattern:
            raise RuntimeError(f"Invalid period: {period}")

        matching_files = []
        for file_path in vault_root.rglob("*.md"):
            if re.match(pattern, file_path.name):
                matching_files.append(file_path)

        # Sort by modification time, most recent first
        matching_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        matching_files = matching_files[:limit]

        results = []
        for file_path in matching_files:
            relative_path = str(file_path.relative_to(vault_root))
            result = {
                "path": relative_path,
                "mtime": file_path.stat().st_mtime
            }

            if include_content:
                try:
                    result["content"] = file_path.read_text(encoding='utf-8')
                except Exception:
                    result["content"] = None

            results.append(result)

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
        days = args.get("days", 90)

        cutoff_time = (datetime.now() - timedelta(days=days)).timestamp()

        recent_files = []
        for file_path in vault_root.rglob("*"):
            if not file_path.is_file() or file_path.name.startswith('.'):
                continue

            mtime = file_path.stat().st_mtime
            if mtime >= cutoff_time:
                recent_files.append({
                    "path": str(file_path.relative_to(vault_root)),
                    "mtime": mtime
                })

        # Sort by mtime descending
        recent_files.sort(key=lambda x: x["mtime"], reverse=True)
        recent_files = recent_files[:limit]

        return [
            TextContent(
                type="text",
                text=json.dumps(recent_files, indent=2)
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

        # Get all file paths
        file_paths = []
        for file_path in vault_root.rglob("*"):
            if file_path.is_file() and not file_path.name.startswith('.'):
                file_paths.append(str(file_path.relative_to(vault_root)))

        # Perform fuzzy matching on filenames
        results = []

        if search_content:
            # Search both filename and content (slower)
            for file_path_str in file_paths:
                # Score based on filename
                filename_score = fuzz.WRatio(query.lower(), file_path_str.lower())

                # If filename score is high enough, include it
                if filename_score >= score_threshold:
                    results.append({
                        'filepath': file_path_str,
                        'score': filename_score,
                        'match_type': 'filename'
                    })
                else:
                    # Try content search for files that didn't match by name
                    try:
                        file_path = get_vault_path(file_path_str)
                        content = file_path.read_text(encoding='utf-8')

                        if content:
                            # Use partial ratio for content matching
                            content_score = fuzz.partial_ratio(query.lower(), content.lower())

                            if content_score >= score_threshold:
                                results.append({
                                    'filepath': file_path_str,
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
        # Find all .base files
        base_files = []
        for file_path in vault_root.rglob("*.base"):
            if not file_path.name.startswith('.'):
                base_files.append(file_path)

        # Parse each base file
        bases_info = []
        for base_path in base_files:
            try:
                content = base_path.read_text(encoding='utf-8')
                relative_path = str(base_path.relative_to(vault_root))

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
                        'filepath': relative_path,
                        'name': base_path.stem,
                        'filters': base_config.get('filters', {}),
                        'filter_properties': sorted(list(filter_properties)),
                        'views': views_info,
                        'all_columns': sorted(list(all_columns))
                    })

            except Exception as e:
                # If we can't parse a base, include it with error info
                bases_info.append({
                    'filepath': str(base_path.relative_to(vault_root)),
                    'name': base_path.stem,
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

        # Find the base file
        base_path = None
        for file_path in vault_root.rglob(f"{base_name}.base"):
            if not file_path.name.startswith('.'):
                base_path = file_path
                break

        if not base_path:
            raise RuntimeError(f"Base '{base_name}' not found in vault")

        # Load and parse the base file
        content = base_path.read_text(encoding='utf-8')

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
            search_path = get_vault_path(target_folder)
            if search_path.exists():
                md_files = list(search_path.rglob("*.md"))
            else:
                md_files = []
        else:
            # If no folder filter, search entire vault
            md_files = list(vault_root.rglob("*.md"))

        # Filter files based on properties
        results = []
        for file_path in md_files[:limit * 2]:  # Get more than needed for filtering
            if file_path.name.startswith('.'):
                continue

            try:
                # Get file content to extract properties
                file_content = file_path.read_text(encoding='utf-8')

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
                        'filepath': str(file_path.relative_to(vault_root)),
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

# =============================================================================
# MCP SERVER SETUP
# =============================================================================

app = Server("mcp-obsidian")

tool_handlers = {}

def add_tool_handler(tool_class: ToolHandler):
    global tool_handlers
    tool_handlers[tool_class.name] = tool_class

def get_tool_handler(name: str) -> ToolHandler | None:
    if name not in tool_handlers:
        return None
    return tool_handlers[name]

# Register all tool handlers
add_tool_handler(ListFilesInDirToolHandler())
add_tool_handler(ListFilesInVaultToolHandler())
add_tool_handler(GetFileContentsToolHandler())
add_tool_handler(SearchToolHandler())
add_tool_handler(PatchContentToolHandler())
add_tool_handler(AppendContentToolHandler())
add_tool_handler(PutContentToolHandler())
add_tool_handler(DeleteFileToolHandler())
add_tool_handler(ComplexSearchToolHandler())
add_tool_handler(BatchGetFileContentsToolHandler())
add_tool_handler(PeriodicNotesToolHandler())
add_tool_handler(RecentPeriodicNotesToolHandler())
add_tool_handler(RecentChangesToolHandler())
add_tool_handler(FuzzySearchToolHandler())
add_tool_handler(ListBasesToolHandler())
add_tool_handler(SearchBasesToolHandler())

@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [th.get_tool_description() for th in tool_handlers.values()]

@app.call_tool()
async def call_tool(name: str, arguments: Any) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
    """Handle tool calls for command line run."""

    if not isinstance(arguments, dict):
        raise RuntimeError("arguments must be dictionary")

    tool_handler = get_tool_handler(name)
    if not tool_handler:
        raise ValueError(f"Unknown tool: {name}")

    try:
        return tool_handler.run_tool(arguments)
    except Exception as e:
        logger.error(str(e))
        raise RuntimeError(f"Caught Exception. Error: {str(e)}")

async def main():
    """Main entry point for the MCP server."""
    # Import here to avoid issues with event loops
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )
