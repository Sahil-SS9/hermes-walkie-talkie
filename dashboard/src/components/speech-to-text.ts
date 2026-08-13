/**
 * Speech-to-text panel with explicit unavailable fallback.
 *
 * The STT feature requires browser SpeechRecognition API support.
 * When unavailable, a clear fallback message is shown instead of
 * a broken or silently missing feature.
 */

export function renderSpeechToText(): HTMLElement {
  const panel = document.createElement('div');
  panel.className = 'wt-stt-panel';
  panel.id = 'wt-stt-panel';

  // Check for SpeechRecognition API
  const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;

  if (!SpeechRecognition) {
    // Explicit unavailable fallback
    panel.innerHTML = `
      <div class="wt-stt-unavailable">
        <span class="wt-stt-icon">🎤</span>
        <div>
          <b>Speech-to-text unavailable</b>
          <p>Your browser does not support the SpeechRecognition API. Use Chrome, Edge, or Safari for voice input.</p>
        </div>
      </div>
    `;
    return panel;
  }

  // Available: render STT UI
  panel.innerHTML = `
    <div class="wt-stt-bar">
      <button class="wt-stt-mic" id="wt-stt-mic" aria-label="Start voice input" title="Start voice input">🎤</button>
      <span class="wt-stt-label">Voice input ready</span>
      <button class="wt-stt-stop" id="wt-stt-stop" style="display:none" aria-label="Stop recording">⏹</button>
    </div>
    <div class="wt-stt-transcript" id="wt-stt-transcript" style="display:none"></div>
    <div class="wt-stt-actions" id="wt-stt-actions" style="display:none">
      <button class="wt-btn wt-btn-primary" id="wt-stt-apply">Apply transcript</button>
      <button class="wt-btn" id="wt-stt-cancel">Cancel</button>
    </div>
  `;

  const micBtn = panel.querySelector('#wt-stt-mic') as HTMLElement;
  const stopBtn = panel.querySelector('#wt-stt-stop') as HTMLElement;
  const transcriptEl = panel.querySelector('#wt-stt-transcript') as HTMLElement;
  const actionsEl = panel.querySelector('#wt-stt-actions') as HTMLElement;
  const applyBtn = panel.querySelector('#wt-stt-apply') as HTMLElement;
  const cancelBtn = panel.querySelector('#wt-stt-cancel') as HTMLElement;

  let recognition: any = null;
  let finalTranscript = '';

  micBtn.onclick = () => {
    try {
      recognition = new SpeechRecognition();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = 'en-US';

      recognition.onresult = (event: any) => {
        let interim = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
          if (event.results[i].isFinal) {
            finalTranscript += event.results[i][0].transcript + ' ';
          } else {
            interim += event.results[i][0].transcript;
          }
        }
        transcriptEl.textContent = finalTranscript + interim;
      };

      recognition.onerror = (event: any) => {
        transcriptEl.textContent = `Error: ${event.error}`;
        resetSTT();
      };

      recognition.onend = () => {
        if (finalTranscript.trim()) {
          actionsEl.style.display = 'flex';
        }
        micBtn.style.display = '';
        stopBtn.style.display = 'none';
      };

      recognition.start();
      micBtn.style.display = 'none';
      stopBtn.style.display = '';
      transcriptEl.style.display = 'block';
      transcriptEl.textContent = 'Listening…';
      finalTranscript = '';
    } catch (err: any) {
      transcriptEl.textContent = `Speech recognition error: ${err.message}`;
      transcriptEl.style.display = 'block';
    }
  };

  stopBtn.onclick = () => {
    if (recognition) {
      recognition.stop();
    }
  };

  applyBtn.onclick = () => {
    // In production, this would send the transcript to the active input
    transcriptEl.textContent = '';
    transcriptEl.style.display = 'none';
    actionsEl.style.display = 'none';
    finalTranscript = '';
  };

  cancelBtn.onclick = () => {
    transcriptEl.textContent = '';
    transcriptEl.style.display = 'none';
    actionsEl.style.display = 'none';
    finalTranscript = '';
  };

  function resetSTT(): void {
    micBtn.style.display = '';
    stopBtn.style.display = 'none';
    actionsEl.style.display = 'none';
  }

  return panel;
}
