from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("register/", views.register_view, name="register"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("profile/", views.profile_view, name="profile"),
    path("listing/<int:listing_id>/", views.listing_detail, name="listing_detail"),
    path("listing/create/", views.create_listing, name="create_listing"),
    path("watchlist/", views.watchlist_view, name="watchlist"),
    path("listing/<int:listing_id>/watchlist/", views.toggle_watchlist, name="toggle_watchlist"),
    path("listing/<int:listing_id>/bid/", views.place_bid, name="place_bid"),
    path("listing/<int:listing_id>/close/", views.close_auction, name="close_auction"),
    path("listing/<int:listing_id>/comment/", views.add_comment, name="add_comment"),
]
