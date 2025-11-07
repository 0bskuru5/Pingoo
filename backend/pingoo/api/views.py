from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from rest_framework.permissions import IsAuthenticated, AllowAny
from .models import Profile, Post, Comment, Notification
from .serializers import (
    UserSerializer, ProfileSerializer, PostSerializer,
    CommentSerializer, NotificationSerializer, UserRegistrationSerializer
)

class UserRegistrationView(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            token, created = Token.objects.get_or_create(user=user)
            return Response({
                'token': token.key,
                'user': UserSerializer(user).data
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UserLoginView(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        user = User.objects.filter(username=username).first()
        
        if user and user.check_password(password):
            login(request, user)
            token, created = Token.objects.get_or_create(user=user)
            return Response({
                'token': token.key,
                'user': UserSerializer(user).data
            })
        return Response(
            {'error': 'Invalid credentials'}, 
            status=status.HTTP_400_BAD_REQUEST
        )

class UserLogoutView(APIView):
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        request.user.auth_token.delete()
        logout(request)
        return Response(status=status.HTTP_200_OK)

class ProfileViewSet(viewsets.ModelViewSet):
    queryset = Profile.objects.all()
    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        username = self.request.query_params.get('username')
        if username:
            return Profile.objects.filter(user__username=username)
        return Profile.objects.all()
    
    @action(detail=True, methods=['post'])
    def follow(self, request, pk=None):
        profile = self.get_object()
        if request.user.profile == profile:
            return Response(
                {'error': 'You cannot follow yourself'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if request.user.profile in profile.followers.all():
            profile.followers.remove(request.user.profile)
            return Response({'status': 'unfollowed'})
        else:
            profile.followers.add(request.user.profile)
            # Create notification
            Notification.objects.create(
                to_user=profile.user,
                from_user=request.user,
                notification_type='follow'
            )
            return Response({'status': 'followed'})

class PostViewSet(viewsets.ModelViewSet):
    queryset = Post.objects.all()
    serializer_class = PostSerializer
    permission_classes = [IsAuthenticated]
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    def get_queryset(self):
        queryset = Post.objects.all()
        user = self.request.query_params.get('user')
        following = self.request.query_params.get('following')
        
        if user:
            queryset = queryset.filter(user__username=user)
        if following and following.lower() == 'true':
            following_users = self.request.user.profile.followers.all()
            queryset = queryset.filter(user__profile__in=following_users)
            
        return queryset.order_by('-created_at')
    
    @action(detail=True, methods=['post'])
    def like(self, request, pk=None):
        post = self.get_object()
        if request.user in post.likes.all():
            post.likes.remove(request.user)
            return Response({'status': 'unliked'})
        else:
            post.likes.add(request.user)
            # Create notification if not the post owner
            if post.user != request.user:
                Notification.objects.create(
                    to_user=post.user,
                    from_user=request.user,
                    notification_type='like',
                    post=post
                )
            return Response({'status': 'liked'})
    
    @action(detail=True, methods=['post'])
    def repost(self, request, pk=None):
        original_post = self.get_object()
        content = request.data.get('content', '')
        
        post = Post.objects.create(
            user=request.user,
            content=content,
            is_repost=True,
            original_post=original_post
        )
        
        # Create notification for the original post owner
        if original_post.user != request.user:
            Notification.objects.create(
                to_user=original_post.user,
                from_user=request.user,
                notification_type='repost',
                post=original_post
            )
        
        serializer = self.get_serializer(post)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

class CommentViewSet(viewsets.ModelViewSet):
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        post_id = self.request.query_params.get('post')
        if post_id:
            return Comment.objects.filter(post_id=post_id).order_by('-created_at')
        return Comment.objects.none()
    
    def perform_create(self, serializer):
        post = get_object_or_404(Post, id=self.request.data.get('post'))
        comment = serializer.save(user=self.request.user, post=post)
        
        # Create notification for the post owner
        if post.user != self.request.user:
            Notification.objects.create(
                to_user=post.user,
                from_user=self.request.user,
                notification_type='comment',
                post=post,
                comment=comment
            )
    
    @action(detail=True, methods=['post'])
    def like(self, request, pk=None):
        comment = self.get_object()
        if request.user in comment.likes.all():
            comment.likes.remove(request.user)
            return Response({'status': 'unliked'})
        else:
            comment.likes.add(request.user)
            # Create notification if not the comment owner
            if comment.user != request.user:
                Notification.objects.create(
                    to_user=comment.user,
                    from_user=request.user,
                    notification_type='like',
                    comment=comment
                )
            return Response({'status': 'liked'})

class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return Notification.objects.filter(to_user=self.request.user).order_by('-created_at')
    
    @action(detail=True, methods=['post'])
    def mark_as_read(self, request, pk=None):
        notification = self.get_object()
        notification.is_read = True
        notification.save()
        return Response({'status': 'marked as read'})
    
    @action(detail=False, methods=['post'])
    def mark_all_as_read(self, request):
        Notification.objects.filter(to_user=request.user, is_read=False).update(is_read=True)
        return Response({'status': 'all notifications marked as read'})
