#!/bin/sh

WEAVIATE_URL="http://weaviate:8080"

echo "Creating TableSchema collection..."
curl -s -X POST "$WEAVIATE_URL/v1/schema" \
  -H "Content-Type: application/json" \
  -d '{
    "class": "TableSchema",
    "vectorizer": "none",
    "description": "Stores table schema definitions as text with embeddings",
    "properties": [
      {
        "name": "table_name",
        "dataType": ["text"],
        "description": "Name of the database table"
      },
      {
        "name": "content",
        "dataType": ["text"],
        "description": "Full schema definition as readable text"
      }
    ]
  }'

echo ""
echo "Creating SqlExample collection..."
curl -s -X POST "$WEAVIATE_URL/v1/schema" \
  -H "Content-Type: application/json" \
  -d '{
    "class": "SqlExample",
    "vectorizer": "none",
    "description": "Stores example question and SQL query pairs with embeddings",
    "properties": [
      {
        "name": "question",
        "dataType": ["text"],
        "description": "Natural language question"
      },
      {
        "name": "sql",
        "dataType": ["text"],
        "description": "Corresponding SQL query"
      }
    ]
  }'

echo ""
echo "Collections created. Verifying..."
curl -s "$WEAVIATE_URL/v1/schema" | grep -o '"class":"[^"]*"'
echo ""
echo "Done."
