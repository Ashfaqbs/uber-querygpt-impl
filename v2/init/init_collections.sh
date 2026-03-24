#!/bin/sh

WEAVIATE_URL="http://weaviate:8080"

echo "Creating WorkspaceTable collection..."
# Stores table schemas scoped to a workspace/domain
curl -s -X POST "$WEAVIATE_URL/v1/schema" \
  -H "Content-Type: application/json" \
  -d '{
    "class": "WorkspaceTable",
    "vectorizer": "none",
    "description": "Table schemas organized by workspace domain",
    "properties": [
      {"name": "table_name",  "dataType": ["text"], "description": "Name of the database table"},
      {"name": "content",     "dataType": ["text"], "description": "Full schema definition as readable text"},
      {"name": "workspace",   "dataType": ["text"], "description": "Business domain workspace this table belongs to"}
    ]
  }'

echo ""
echo "Creating WorkspaceSqlExample collection..."
# Stores SQL examples scoped to a workspace/domain
curl -s -X POST "$WEAVIATE_URL/v1/schema" \
  -H "Content-Type: application/json" \
  -d '{
    "class": "WorkspaceSqlExample",
    "vectorizer": "none",
    "description": "SQL examples organized by workspace domain",
    "properties": [
      {"name": "question",  "dataType": ["text"], "description": "Natural language question"},
      {"name": "sql",       "dataType": ["text"], "description": "Corresponding SQL query"},
      {"name": "workspace", "dataType": ["text"], "description": "Business domain workspace this example belongs to"}
    ]
  }'

echo ""
echo "Creating WorkspaceRegistry collection..."
# Stores workspace definitions — intent agent uses this to classify questions
curl -s -X POST "$WEAVIATE_URL/v1/schema" \
  -H "Content-Type: application/json" \
  -d '{
    "class": "WorkspaceRegistry",
    "vectorizer": "none",
    "description": "Registry of available workspaces with their descriptions for intent classification",
    "properties": [
      {"name": "workspace",   "dataType": ["text"], "description": "Workspace name/identifier"},
      {"name": "description", "dataType": ["text"], "description": "What this workspace covers — used for intent matching"},
      {"name": "tables",      "dataType": ["text[]"], "description": "List of table names in this workspace"}
    ]
  }'

echo ""
echo "Verifying collections..."
curl -s "$WEAVIATE_URL/v1/schema" | grep -o '"class":"[^"]*"'
echo ""
echo "Done."
