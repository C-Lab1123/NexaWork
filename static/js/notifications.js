(() => {
  const badge = document.querySelector(".notification-pill");
  if (!badge) return;
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
  let socket;
  let delay = 1000;
  let pollAfter = Number(badge.dataset.latestId || 0);
  let polling = false;
  let pollTimer;
  const seenIds = new Set();

  const showToast = item => {
    const id = Number(item.id);
    if (!Number.isSafeInteger(id) || id <= 0) return;
    if (seenIds.has(id)) return;
    seenIds.add(id);
    pollAfter = Math.max(pollAfter, id);
    showAnnouncement(item);
    if (item.title.startsWith("Meeting invitation: ")) refreshMeetings();
    let stack = document.querySelector(".live-toast-stack");
    if (!stack) {
      stack = document.createElement("div");
      stack.className = "live-toast-stack";
      stack.setAttribute("aria-live", "polite");
      document.body.append(stack);
    }
    const toast = document.createElement("div");
    toast.className = "live-toast";
    const title = document.createElement("strong");
    title.textContent = item.title;
    const body = document.createElement("p");
    body.textContent = item.body;
    toast.append(title, body);
    const target = new URL(item.url || "/notifications/", window.location.origin);
    if (target.origin === window.location.origin) {
      const link = document.createElement("a");
      link.href = `${target.pathname}${target.search}${target.hash}`;
      link.textContent = "Open notification →";
      toast.append(link);
    }
    stack.append(toast);
    window.setTimeout(() => toast.remove(), 8000);
    const count = Number((badge.textContent.match(/\d+/) || ["0"])[0]) + 1;
    badge.textContent = `● ${count}`;
  };

  const showAnnouncement = item => {
    if (!item.title.startsWith("Announcement: ")) return;
    const titleText = item.title.slice("Announcement: ".length);
    document.querySelectorAll("[data-live-announcements]").forEach(list => {
      list.querySelector(".empty-state")?.remove();
      const card = document.createElement("article");
      const heading = document.createElement("h2");
      heading.textContent = titleText;
      const body = document.createElement("p");
      body.textContent = item.body;
      if (list.dataset.liveAnnouncements === "preview") {
        card.className = "announcement-preview";
        const dot = document.createElement("span");
        dot.className = "announcement-dot";
        const content = document.createElement("div");
        const previewHeading = document.createElement("h3");
        previewHeading.textContent = titleText;
        const previewBody = document.createElement("p");
        previewBody.textContent = item.body;
        const date = document.createElement("small");
        date.textContent = "Just now";
        content.append(previewHeading, previewBody, date);
        card.append(dot, content);
        list.querySelector(".panel-heading")?.insertAdjacentElement("afterend", card);
      } else {
        card.className = "panel announcement-card";
        const top = document.createElement("div");
        top.className = "announcement-card-top";
        const icon = document.createElement("span");
        icon.className = "announcement-icon";
        icon.textContent = "▤";
        const title = document.createElement("div");
        title.append(heading);
        const date = document.createElement("small");
        date.textContent = "Just now";
        title.append(date);
        top.append(icon, title);
        const content = document.createElement("div");
        content.className = "announcement-body";
        body.style.whiteSpace = "pre-line";
        content.append(body);
        const author = document.createElement("div");
        author.className = "announcement-author";
        author.textContent = "Posted by NexaWork";
        card.append(top, content, author);
        list.prepend(card);
      }
    });
  };

  const refreshMeetings = async () => {
    if (!document.querySelector("[data-live-meetings]")) return;
    try {
      const response = await fetch("/meetings/updates/", {
        headers: { Accept: "application/json" },
        credentials: "same-origin"
      });
      if (!response.ok) {
        console.error("Could not refresh scheduled meetings.", response.status);
        return;
      }
      const data = await response.json();
      data.meetings.forEach(showMeeting);
    } catch (error) {
      console.error("Could not refresh scheduled meetings.", error);
    }
  };

  const showMeeting = meeting => {
    document.querySelectorAll("[data-live-meetings]").forEach(list => {
      if (list.querySelector(`[data-meeting-id="${meeting.id}"]`)) return;
      list.querySelector(".empty-state")?.remove();

      const startsAt = new Date(meeting.starts_at);
      if (Number.isNaN(startsAt.getTime())) return;
      const day = String(startsAt.getDate()).padStart(2, "0");
      const month = startsAt.toLocaleString(undefined, { month: "short" }).toUpperCase();
      const weekday = startsAt.toLocaleString(undefined, { weekday: "long" });
      const time = startsAt.toLocaleTimeString(undefined, {
        hour: "numeric",
        minute: "2-digit"
      });
      const link = document.createElement("a");
      link.dataset.meetingId = meeting.id;
      link.href = meeting.url;

      if (list.dataset.liveMeetings === "preview") {
        link.className = "meeting-preview";
        const date = document.createElement("span");
        date.className = "meeting-date";
        const dateDay = document.createElement("b");
        dateDay.textContent = day;
        const dateMonth = document.createElement("small");
        dateMonth.textContent = month;
        date.append(dateDay, dateMonth);
        const content = document.createElement("span");
        content.className = "meeting-copy";
        const title = document.createElement("strong");
        title.textContent = meeting.title;
        const details = document.createElement("small");
        details.textContent = `${weekday} · ${time} · ${meeting.meeting_type}`;
        content.append(title, details);
        const arrow = document.createElement("span");
        arrow.className = "meeting-chevron";
        arrow.textContent = "›";
        link.append(date, content, arrow);
        list.querySelector(".panel-heading")?.insertAdjacentElement("afterend", link);
      } else {
        link.className = "meeting-list-card";
        const date = document.createElement("span");
        date.className = "meeting-date large";
        const dateDay = document.createElement("b");
        dateDay.textContent = day;
        const dateMonth = document.createElement("small");
        dateMonth.textContent = month;
        date.append(dateDay, dateMonth);
        const content = document.createElement("span");
        content.className = "meeting-list-copy";
        const title = document.createElement("strong");
        title.textContent = meeting.title;
        const details = document.createElement("small");
        details.textContent = `${weekday}, ${startsAt.toLocaleString(undefined, {
          month: "long",
          day: "numeric"
        })} · ${time} · Hosted by ${meeting.host} · ${meeting.meeting_type}`;
        content.append(title, details);
        if (meeting.description) {
          const description = document.createElement("span");
          description.textContent = meeting.description.length > 130
            ? `${meeting.description.slice(0, 127)}…`
            : meeting.description;
          content.append(description);
        }
        const action = document.createElement("span");
        action.className = "button button-outline small-button";
        action.textContent = "Open meeting →";
        link.append(date, content, action);
        list.prepend(link);
      }
    });
  };

  const poll = async () => {
    if (polling) return;
    polling = true;
    try {
      const response = await fetch(`/notifications/updates/?after=${pollAfter}`, {
        headers: { Accept: "application/json" },
        credentials: "same-origin"
      });
      if (!response.ok) return;
      const data = await response.json();
      data.notifications.forEach(notification => {
        showToast(notification);
        pollAfter = Math.max(pollAfter, Number(notification.id));
      });
    } catch (error) {
      console.error("Could not check for new notifications.", error);
    } finally {
      polling = false;
    }
  };

  const startPolling = () => {
    if (pollTimer) return;
    poll();
    pollTimer = window.setInterval(poll, 1000);
  };

  const connect = () => {
    if (!("WebSocket" in window)) {
      startPolling();
      return;
    }
    socket = new WebSocket(`${scheme}//${window.location.host}/ws/notifications/`);
    socket.addEventListener("open", () => {
      delay = 1000;
      poll();
    });
    socket.addEventListener("message", event => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "notification.created") showToast(data);
      } catch (error) {
        console.error("Could not read a live notification.", error);
      }
    });
    socket.addEventListener("close", () => {
      startPolling();
      window.setTimeout(connect, delay);
      delay = Math.min(delay * 2, 30000);
    });
  };
  connect();
  startPolling();
})();
