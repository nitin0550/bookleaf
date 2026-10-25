from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from .models import User
from .permissions import IsAdmin
from .serializers import LoginSerializer, StaffMemberSerializer, UserSerializer


class LoginView(APIView):
    """Exchange email + password for an API token."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [AnonRateThrottle]

    @extend_schema(request=LoginSerializer, responses={200: UserSerializer}, auth=[])
    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, "user": UserSerializer(user).data})


class LogoutView(APIView):
    """Revoke the current token."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class StaffListView(generics.ListAPIView):
    """Admins only: list of staff members, used for ticket assignment."""

    permission_classes = [IsAdmin]
    serializer_class = StaffMemberSerializer
    pagination_class = None
    queryset = User.objects.filter(role=User.Role.ADMIN, is_active=True).order_by("full_name")
