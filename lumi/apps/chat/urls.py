from django.urls import path

from apps.chat import views

urlpatterns = [
    path("chat", views.ChatView.as_view(), name="chat"),
    path("chat/stream", views.ChatStreamView.as_view(), name="chat-stream"),
    path("chat/history", views.ChatHistoryView.as_view(), name="chat-history"),
    path("chat/title", views.ChatTitleView.as_view(), name="chat-title"),
]
