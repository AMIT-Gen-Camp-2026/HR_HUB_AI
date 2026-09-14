"""Blueprint package. Each routes_*.py module owns exactly one Flask Blueprint and
contains NO business logic — a route only parses the request, calls into
app.pipeline, and returns the Pydantic result as JSON. If you find yourself writing
an if/else about claim status inside a route file, it belongs in app/pipeline instead."""
