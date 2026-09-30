# A FastAPI application that simulates a takeaway ordering system, providing endpoints to view the menu, 
# view orders, and place new orders, with input validation and error handling for insufficient stock and item not found scenarios.

from contextlib import asynccontextmanager

# Standard library imports
from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

# Local imports
from kitchen import simulate_queue
from staff_auth import require_staff

from database import (
    DATABASE_PATH, InsufficientStockError, ItemNotFoundError,
    checkout, get_menu, get_orders, initialise_database, place_order,
    update_order_status,
)

# A Pydantic model to define and validate the JSON structure that clients must send when placing an order, ensuring that item_id is a 
# positive integer and quantity is between 1 and 50

class OrderRequest(BaseModel):
    """Define and validate the JSON a client must send."""
    model_config = ConfigDict(extra="forbid")
    item_id: int = Field(strict=True, gt=0)
    quantity: int = Field(strict=True, ge=1, le=50)


class StatusUpdateRequest(BaseModel):
    """Define and validate an order-status update sent by a client."""
    model_config = ConfigDict(extra="forbid")
    status: str = Field(strict=True, min_length=1)


class TrolleyItemRequest(BaseModel):
    """One product and quantity inside a customer's trolley."""
    model_config = ConfigDict(extra="forbid")
    item_id: int = Field(strict=True, gt=0)
    quantity: int = Field(strict=True, ge=1, le=50)


class CheckoutRequest(BaseModel):
    """A complete trolley submitted as one order."""
    model_config = ConfigDict(extra="forbid")
    items: list[TrolleyItemRequest] = Field(min_length=1, max_length=20)


class TrackingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tracking_code: str = Field(strict=True, min_length=1, max_length=128)

# A function to create and configure the FastAPI application, including defining the lifespan context manager to initialise the database, 
# and setting up the endpoints for home, menu, orders, and placing an order with appropriate error handling

def create_app(database_path=DATABASE_PATH):
    """Tests can supply a temporary database instead of the user's data."""
    @asynccontextmanager
    async def lifespan(application):
        initialise_database(database_path)
        yield

    application = FastAPI(
        title="Takeaway Ordering Simulator",
        description="Educational mock API using fictional data; no payments.",
        version="0.5.0",
        lifespan=lifespan,
    )

# Define the endpoints for the FastAPI application, including the home endpoint that returns a welcome message and documentation link,
# the menu endpoint that returns the current menu items, the orders endpoint that returns all saved orders, and the order endpoint
# that allows clients to place a new order, handling errors for item not found and insufficient stock
# "@application.get("/")" defines the home endpoint that returns a welcome message and a link to the API documentation.

    @application.get("/")
    def home():
        return {"message": "Takeaway mock API", "documentation": "/docs"}

    @application.get("/menu")
    def menu_endpoint():
        return get_menu(database_path)

    @application.middleware("http")
    async def private_responses(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @application.post("/track")
    def track_endpoint(request: TrackingRequest):
        orders = get_orders(database_path, tracking_code=request.tracking_code)
        if not orders:
            raise HTTPException(404, "Order not found. Check your tracking code.")
        return orders[0]

    @application.get("/staff/session", dependencies=[Depends(require_staff)])
    def staff_session():
        return {"authenticated": True}

    @application.get("/orders", dependencies=[Depends(require_staff)])
    def orders_endpoint():
        return get_orders(database_path)

    # Read saved orders and simulate timing without changing stock or status.
    @application.get("/queue", dependencies=[Depends(require_staff)])
    def queue_endpoint(stations: int = Query(default=2, ge=1, le=10)):
        try:
            return simulate_queue(get_orders(database_path), stations)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.post("/orders", status_code=201)
    def order_endpoint(order: OrderRequest):
        try:
            return place_order(order.item_id, order.quantity, database_path)
        except ItemNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except InsufficientStockError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.post("/checkout", status_code=201)
    def checkout_endpoint(request: CheckoutRequest):
        try:
            return checkout(
                [item.model_dump() for item in request.items],
                database_path,
            )
        except ItemNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except InsufficientStockError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.patch("/orders/{order_id}/status", dependencies=[Depends(require_staff)])
    def status_endpoint(order_id: int, update: StatusUpdateRequest):
        try:
            return update_order_status(order_id, update.status, database_path)
        except ValueError as error:
            if str(error) == "Order not found.":
                raise HTTPException(status_code=404, detail=str(error)) from error
            raise HTTPException(status_code=409, detail=str(error)) from error

    return application

# Create the FastAPI application instance using the create_app function, 
# which can be used by an ASGI server to run the application.
app = create_app()
