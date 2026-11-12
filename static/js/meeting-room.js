import { Room, RoomEvent, Track } from "https://cdn.jsdelivr.net/npm/livekit-client@2.9.9/dist/livekit-client.esm.mjs";

const configNode = document.getElementById("meeting-config");
const videos = document.getElementById("livekit-videos");
const status = document.getElementById("livekit-status");
const enableAudio = document.getElementById("enable-audio");

if (configNode && videos && status && enableAudio) {
  const config = JSON.parse(configNode.textContent);
  const room = new Room({
    adaptiveStream: true,
    dynacast: true,
    audioCaptureDefaults: {
      autoGainControl: true,
      echoCancellation: true,
      noiseSuppression: true,
      voiceIsolation: true,
    },
  });
  const attachedTracks = new Set();

  const setPlaceholder = (title, description) => {
    let placeholder = videos.querySelector(".livekit-placeholder");
    if (!placeholder) {
      placeholder = document.createElement("div");
      placeholder.className = "livekit-placeholder";
      const icon = document.createElement("span");
      icon.textContent = "◉";
      const heading = document.createElement("strong");
      const detail = document.createElement("small");
      placeholder.append(icon, heading, detail);
      videos.append(placeholder);
    }
    placeholder.querySelector("strong").textContent = title;
    placeholder.querySelector("small").textContent = description;
  };

  const renderTrack = (track, participant, isLocal = false) => {
    if (attachedTracks.has(track)) return;
    const element = track.attach();
    attachedTracks.add(track);
    element.dataset.participant = participant.sid;
    if (track.kind === Track.Kind.Video) {
      element.className = "participant-video";
      element.autoplay = true;
      element.playsInline = true;
      if (isLocal) element.muted = true;
      videos.querySelector(".livekit-placeholder")?.remove();
      videos.append(element);
    } else {
      element.autoplay = true;
      element.hidden = true;
      videos.append(element);
    }
  };

  const setParticipantAudioTrack = (identity, trackSid) => {
    const form = [...document.querySelectorAll("[data-mute-form]")]
      .find(item => item.dataset.identity === identity);
    if (!form) return;
    form.elements.track_sid.value = trackSid || "";
    form.querySelector("[data-mute-button]").disabled = !trackSid;
  };
  const setParticipantMediaStatus = (identity, message) => {
    const row = [...document.querySelectorAll("[data-media-identity]")]
      .find(item => item.dataset.mediaIdentity === identity);
    const mediaStatus = row?.querySelector("[data-media-status]");
    if (mediaStatus) mediaStatus.textContent = message;
  };
  const hasRemoteAudio = () => [...room.remoteParticipants.values()]
    .some(participant => [...participant.audioTrackPublications.values()]
      .some(publication => publication.track && !publication.isMuted));

  room.on(RoomEvent.TrackSubscribed, (track, publication, participant) => {
    renderTrack(track, participant);
    if (track.kind === Track.Kind.Audio) {
      setParticipantAudioTrack(participant.identity, publication.trackSid);
      setParticipantMediaStatus(
        participant.identity,
        publication.isMuted ? "Live call connected · microphone muted" : "Receiving microphone audio"
      );
    }
  });
  room.on(RoomEvent.AudioPlaybackStatusChanged, () => {
    if (!room.canPlaybackAudio) {
      status.textContent = "Audio is blocked by your browser · select Enable audio";
    }
  });
  room.on(RoomEvent.ParticipantConnected, participant => {
    setParticipantMediaStatus(participant.identity, "Live call connected · waiting for microphone");
  });
  room.on(RoomEvent.ParticipantDisconnected, participant => {
    setParticipantMediaStatus(participant.identity, "Disconnected from live call");
  });
  room.on(RoomEvent.TrackUnsubscribed, (track, publication, participant) => {
    track.detach().forEach(element => element.remove());
    attachedTracks.delete(track);
    videos.querySelector(`[data-participant="${participant.sid}"]`)?.remove();
    if (track.kind === Track.Kind.Audio) {
      setParticipantAudioTrack(participant.identity, "");
      setParticipantMediaStatus(participant.identity, "Live call connected · microphone unavailable");
    }
  });
  room.on(RoomEvent.Disconnected, () => { status.textContent = "Disconnected"; });
  room.on(RoomEvent.ParticipantDisconnected, participant =>
    videos.querySelectorAll(`[data-participant="${participant.sid}"]`).forEach(element => element.remove()));

  const setControl = (id, label, action) => {
    const button = document.getElementById(id);
    if (button) button.addEventListener("click", async () => {
      try {
        await action();
        button.querySelector("span").textContent = label();
      } catch (error) {
        status.textContent = "A device control could not be changed.";
        console.error("NexaWork meeting control failed", error);
      }
    });
  };

  enableAudio.addEventListener("click", async () => {
    enableAudio.disabled = true;
    try {
      await room.startAudio();
      status.textContent = room.canPlaybackAudio
        ? (hasRemoteAudio() ? "Audio playback enabled" : "Audio enabled · waiting for a participant’s microphone")
        : "Audio is still blocked by your browser.";
    } catch (error) {
      status.textContent = "Connected · select Enable audio to hear other participants.";
      console.error("NexaWork audio playback could not be enabled", error);
    } finally {
      enableAudio.disabled = false;
    }
  });

  setControl("toggle-mic", () => room.localParticipant.isMicrophoneEnabled ? "Mute" : "Unmute",
    () => room.localParticipant.setMicrophoneEnabled(!room.localParticipant.isMicrophoneEnabled));
  setControl("toggle-camera", () => room.localParticipant.isCameraEnabled ? "Camera off" : "Camera on",
    () => room.localParticipant.setCameraEnabled(!room.localParticipant.isCameraEnabled));
  setControl("toggle-share", () => room.localParticipant.isScreenShareEnabled ? "Stop sharing" : "Share screen",
    () => room.localParticipant.setScreenShareEnabled(!room.localParticipant.isScreenShareEnabled));

  document.querySelectorAll("[data-mute-form]").forEach(form => {
    const button = form.querySelector("[data-mute-button]");
    button.addEventListener("click", async () => {
      const mutedField = form.elements.muted;
      try {
        const response = await fetch(form.action, {
          method: "POST",
          body: new FormData(form),
          headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Mute request failed");
        mutedField.value = String(!result.muted);
        button.textContent = result.muted ? "Unmute microphone" : "Mute microphone";
      } catch (error) {
        status.textContent = "Could not change this participant’s microphone state.";
        console.error("NexaWork participant mute failed", error);
      }
    });
  });

  try {
    await room.connect(config.url, config.token);
    const meetingType = document.body.dataset.meetingType;
    status.textContent = meetingType === "audio"
      ? "Connected · audio meeting"
      : "Connected · video meeting";
    setPlaceholder(
      meetingType === "audio" ? "Audio meeting connected" : "Video meeting connected",
      meetingType === "audio"
        ? "Your camera is off. Waiting for participants to join."
        : "Waiting for participants to join."
    );
    try {
      await room.localParticipant.setMicrophoneEnabled(true);
      setParticipantMediaStatus(
        room.localParticipant.identity,
        room.localParticipant.audioTrackPublications.size
          ? "Live call connected · microphone on"
          : "Live call connected · microphone not published"
      );
    } catch (error) {
      status.textContent = "Connected · microphone access unavailable";
      setParticipantMediaStatus(room.localParticipant.identity, "Live call connected · microphone unavailable");
      console.error("NexaWork microphone access failed", error);
    }
    if (meetingType !== "audio") {
      try {
        await room.localParticipant.setCameraEnabled(true);
        for (const publication of room.localParticipant.videoTrackPublications.values()) {
          if (publication.track) renderTrack(publication.track, room.localParticipant, true);
        }
      } catch (error) {
        setPlaceholder(
          "Video meeting connected",
          "Camera access is unavailable. You can still hear other participants."
        );
        status.textContent = "Connected · camera access unavailable";
        console.error("NexaWork camera access failed", error);
      }
    }
    for (const publication of room.remoteParticipants.values()) {
      setParticipantMediaStatus(publication.identity, "Live call connected · waiting for microphone");
      for (const trackPublication of publication.trackPublications.values()) {
        if (trackPublication.track) {
          renderTrack(trackPublication.track, publication);
          if (trackPublication.kind === Track.Kind.Audio) {
            setParticipantAudioTrack(publication.identity, trackPublication.trackSid);
            setParticipantMediaStatus(
              publication.identity,
              trackPublication.isMuted ? "Live call connected · microphone muted" : "Receiving microphone audio"
            );
          }
        }
      }
    }
  } catch (error) {
    const reason = error instanceof Error ? error.message : "Unknown connection error";
    status.textContent = `Could not connect to the live meeting: ${reason}`;
    console.error("NexaWork meeting connection failed", error);
    setPlaceholder(
      "Could not connect to the meeting",
      "Check the LiveKit URL, network, and meeting access, then try again."
    );
    console.error("NexaWork meeting connection failed", error);
  }
}
