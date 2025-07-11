"""`Project` uses this backend to interact with the Notion API."""

__all__ = ["NotionBackend", "get_page_id", "get_database_id"]

import os
import typing as t

from fastcore.utils import patch, patch_to
from notion_client import Client as NotionClient

from ..exceptions import DuplicateError, NotFoundError


class NotionBackend:
    """A backend for interacting with the Notion API"""

    def __init__(
        self, root_page_id: str, notion_client: t.Optional[NotionClient] = None
    ):
        self.root_page_id = root_page_id
        if notion_client is None:
            self.client = NotionClient(auth=os.getenv("NOTION_API_KEY"))
        else:
            self.client = notion_client

    def __repr__(self):
        return f"NotionBackend(root_page_id={self.root_page_id})"

    def validate_project_structure(self, root_page_id):
        """
        Validate the project structure by checking if the root page exists and has the correct sub-pages.
        Structure is as follows:
        - Root Page
        - Datasets
        - Experiments
        - Comparisons
        """
        # Check if root page exists
        if not self.page_exists(root_page_id):
            return False

        # Search for required sub-pages under root
        required_pages = {"Datasets", "Experiments", "Comparisons"}
        found_pages = set()

        # Search for child pages
        children = self.client.blocks.children.list(root_page_id)
        for block in children["results"]:
            if block["type"] == "child_page":
                found_pages.add(block["child_page"]["title"])

        # Verify all required pages exist
        return required_pages.issubset(found_pages)

    def create_new_page(self, parent_page_id, page_name) -> str:
        """
        Create a new page inside the given parent page and return the page id.

        Args:
            parent_page_id (str): The ID of the parent page
            page_name (str): The title for the new page

        Returns:
            str: The ID of the newly created page

        Raises:
            ValueError: If the parent page does not exist
        """
        # First check if parent page exists
        if not self.page_exists(parent_page_id):
            raise ValueError(f"Parent page {parent_page_id} does not exist")

        # Create a new child page
        response = self.client.pages.create(
            parent={"type": "page_id", "page_id": parent_page_id},
            properties={"title": [{"type": "text", "text": {"content": page_name}}]},
        )

        # Return the ID of the newly created page
        return response["id"]

    def page_exists(self, page_id):
        """Check if a page exists by attempting to retrieve it."""
        try:
            self.client.pages.retrieve(page_id)
            return True
        except Exception:
            return False

    def create_new_database(
        self, parent_page_id: str, title: str, properties: dict
    ) -> str:
        """Create a new database inside the given parent page.

        Args:
            parent_page_id (str): The ID of the parent page
            title (str): The title for the new database
            properties (dict): The database properties definition

        Returns:
            str: The ID of the newly created database
        """
        response = self.client.databases.create(
            parent={"type": "page_id", "page_id": parent_page_id},
            title=[{"type": "text", "text": {"content": title}}],
            properties=properties,
        )
        return response["id"]


@t.overload
def get_page_id(
    self, parent_id: str, page_name: str, return_multiple: t.Literal[False] = False
) -> str: ...
@t.overload
def get_page_id(
    self, parent_id: str, page_name: str, return_multiple: t.Literal[True]
) -> t.List[str]: ...
@patch_to(NotionBackend)
def get_page_id(
    self, parent_id: str, page_name: str, return_multiple: bool = False
) -> t.Union[str, t.List[str]]:
    """Get page ID(s) by name under a parent page.

    Args:
        parent_id (str): The ID of the parent page to search under
        page_name (str): The title of the page to find
        return_multiple (bool): If True, returns all matching page IDs

    Returns:
        Union[str, List[str]]: Single page ID or list of page IDs

    Raises:
        DuplicateError: If return_multiple is False and multiple pages found
        ValueError: If no pages found
    """
    matching_pages = []
    next_cursor = None

    while True:
        # Get page of results, using cursor if we have one
        response = self.client.blocks.children.list(parent_id, start_cursor=next_cursor)

        # Check each block in current page
        for block in response["results"]:
            if (
                block["type"] == "child_page"
                and block["child_page"]["title"] == page_name
            ):
                matching_pages.append(block["id"])

        # Check if there are more results
        if not response.get("has_more", False):
            break

        next_cursor = response.get("next_cursor")

    if not matching_pages:
        raise NotFoundError(f"No page found with name '{page_name}'")

    if return_multiple:
        return matching_pages
    else:
        if len(matching_pages) > 1:
            raise DuplicateError(f"Multiple pages found with name '{page_name}'")
        return matching_pages[0]


@t.overload
def get_database_id(
    self, parent_page_id: str, name: str, return_multiple: t.Literal[False] = False
) -> str: ...
@t.overload
def get_database_id(
    self, parent_page_id: str, name: str, return_multiple: t.Literal[True]
) -> t.List[str]: ...
@patch_to(NotionBackend)
def get_database_id(
    self, parent_page_id: str, name: str, return_multiple: bool = False
) -> t.Union[str, t.List[str]]:
    """Get the database ID(s) by name under a parent page.

    Args:
        parent_page_id (str): The ID of the parent page to search under
        name (str): The name of the database to find
        return_multiple (bool): If True, returns all matching database IDs

    Returns:
        Union[str, List[str]]: Single database ID or list of database IDs

    Raises:
        NotFoundError: If no database found with given name
        DuplicateError: If return_multiple is False and multiple databases found
    """
    matching_databases = []
    next_cursor = None

    while True:
        response = self.client.blocks.children.list(
            parent_page_id, start_cursor=next_cursor
        )

        for block in response["results"]:
            if block["type"] == "child_database":
                database = self.client.databases.retrieve(database_id=block["id"])
                if database["title"][0]["plain_text"].lower() == name.lower():
                    matching_databases.append(block["id"])

        if not response.get("has_more", False):
            break

        next_cursor = response.get("next_cursor")

    if not matching_databases:
        raise NotFoundError(f"No database found with name '{name}'")

    if return_multiple:
        return matching_databases
    else:
        if len(matching_databases) > 1:
            raise DuplicateError(f"Multiple databases found with name '{name}'")
        return matching_databases[0]


@patch
def create_page_in_database(
    self: NotionBackend,
    database_id: str,
    properties: dict,
    parent: t.Optional[dict] = None,
) -> dict:
    """Create a new page in a database.

    Args:
        database_id: The ID of the database to create the page in
        properties: The page properties
        parent: Optional parent object (defaults to database parent)

    Returns:
        dict: The created page object
    """
    if parent is None:
        parent = {"type": "database_id", "database_id": database_id}

    # Remove any unique_id properties as they cannot be updated directly
    filtered_properties = {
        k: v
        for k, v in properties.items()
        if not (isinstance(v, dict) and v.get("type") == "unique_id")
    }

    response = self.client.pages.create(parent=parent, properties=filtered_properties)

    return response


@patch
def get_database(self: NotionBackend, database_id: str) -> dict:
    """Get a database by ID.

    Args:
        database_id: The ID of the database to retrieve

    Returns:
        dict: The database object
    """
    return self.client.databases.retrieve(database_id=database_id)


@patch
def query_database(
    self: NotionBackend,
    database_id: str,
    filter: t.Optional[dict] = None,
    sorts: t.Optional[t.List[dict]] = None,
    archived: bool = False,
) -> dict:
    """Query a database with optional filtering and sorting.

    Args:
        database_id: The ID of the database to query
        filter: Optional filter conditions
        sorts: Optional sort conditions
        archived: If True, include archived pages. If False, only return non-archived pages

    Returns:
        dict: Query response containing all results
    """
    query_params = {
        "database_id": database_id,
        "page_size": 100,  # Maximum allowed by Notion API
    }

    if filter:
        query_params["filter"] = filter
    if sorts:
        query_params["sorts"] = sorts

    # Initialize results
    all_results = []
    has_more = True
    next_cursor = None

    # Fetch all pages
    while has_more:
        if next_cursor:
            query_params["start_cursor"] = next_cursor

        response = self.client.databases.query(**query_params)

        # Filter results based on archived status
        filtered_results = [
            page
            for page in response["results"]
            if page.get("archived", False) == archived
        ]
        all_results.extend(filtered_results)

        has_more = response.get("has_more", False)
        next_cursor = response.get("next_cursor")

    # Return combined results
    return {"results": all_results, "has_more": False, "next_cursor": None}


@patch
def update_page(
    self: NotionBackend,
    page_id: str,
    properties: t.Optional[t.Dict[str, t.Any]] = None,
    archived: bool = False,
) -> dict:
    """Update a page's properties and/or archive status.

    Args:
        page_id: The ID of the page to update
        properties: Optional properties to update
        archived: Whether to archive the page

    Returns:
        dict: The updated page object
    """
    update_params = {"page_id": page_id}

    if properties:
        # Remove any unique_id properties as they cannot be updated directly
        filtered_properties = {
            k: v
            for k, v in properties.items()
            if not (isinstance(v, dict) and v.get("type") == "unique_id")
        }
        update_params["properties"] = filtered_properties

    if archived:
        update_params["archived"] = True  # type: ignore

    return self.client.pages.update(**update_params)
