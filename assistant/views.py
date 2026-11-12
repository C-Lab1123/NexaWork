from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import AssistantExchange


def _workplace_answer(question):
    text = question.lower()
    if any(word in text for word in ("channel", "chat", "message")):
        return "Open Channels to find organization-wide conversations. Private channels are visible only to their members."
    if any(word in text for word in ("meeting", "call", "video", "audio")):
        return "Open Meetings to view upcoming sessions. A meeting host or workplace administrator can manage participants."
    if any(word in text for word in ("file", "document", "download")):
        return "Open Files to browse resources shared with your organization. Restricted files are available only to selected people."
    if any(word in text for word in ("announcement", "news", "update")):
        return "Workplace updates are available from Announcements. Branch-specific notices are shown to people in that branch."
    if any(word in text for word in ("employee", "team", "department", "branch", "organization")):
        return "Your workplace profile is managed by your employer. Contact your workplace administrator if your organization details need updating."
    return (
        "I can help you find channels, meetings, files, announcements, or workplace information. "
        "Ask about one of those topics to get started."
    )


@login_required
def assistant_home(request):
    answer = ""
    if request.method == "POST":
        question = request.POST.get("question", "").strip()
        if question:
            answer = _workplace_answer(question[:1000])
            AssistantExchange.objects.create(user=request.user, question=question[:1000], answer=answer)
    history = AssistantExchange.objects.filter(user=request.user)[:10]
    return render(request, "assistant/home.html", {"answer": answer, "history": history})
