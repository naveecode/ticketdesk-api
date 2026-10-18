from django.urls import path

from accounts.views import (
    MeView,
    RegisterView,
    ThrottledTokenObtainPairView,
    ThrottledTokenRefreshView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("token/", ThrottledTokenObtainPairView.as_view(), name="token_obtain"),
    path("token/refresh/", ThrottledTokenRefreshView.as_view(), name="token_refresh"),
    path("me/", MeView.as_view(), name="me"),
]
