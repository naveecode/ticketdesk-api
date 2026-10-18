from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from accounts.serializers import (
    RegisterSerializer,
    TicketdeskTokenObtainPairSerializer,
    UserSerializer,
)
from accounts.throttles import AuthRateThrottle


@extend_schema(tags=["auth"], auth=[], request=RegisterSerializer, responses=UserSerializer)
class RegisterView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [AuthRateThrottle]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


@extend_schema_view(post=extend_schema(tags=["auth"], auth=[]))
class ThrottledTokenObtainPairView(TokenObtainPairView):
    serializer_class = TicketdeskTokenObtainPairSerializer
    throttle_classes = [AuthRateThrottle]


@extend_schema_view(post=extend_schema(tags=["auth"], auth=[]))
class ThrottledTokenRefreshView(TokenRefreshView):
    throttle_classes = [AuthRateThrottle]


@extend_schema(tags=["auth"], responses=UserSerializer)
class MeView(APIView):
    def get(self, request):
        return Response(UserSerializer(request.user).data)
