/**
 * Multilingual Voice Assistant Service & Website Controller
 * Supports English (en-US), Hindi (hi-IN), Kannada (kn-IN), Tamil (ta-IN), Telugu (te-IN)
 * Controls DNAura website navigation, analysis execution, recommendations, and sensitive confirmations.
 */

window.VoiceAssistant = {
    speechRecognition: null,
    speechSynth: window.speechSynthesis,
    isListening: false,
    isProcessingCommand: false,
    autoSpeakEnabled: true,
    pendingAction: null,
    userCoords: null,

    isSpeaking: false,
    keepAliveInterval: null,
    voicesCache: [],

    // Language BCP47 Mapping
    langCodes: {
        'en': 'en-US',
        'hi': 'hi-IN',
        'kn': 'kn-IN',
        'te': 'te-IN',
        'ta': 'ta-IN'
    },

    init: function() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (SpeechRecognition) {
            this.speechRecognition = new SpeechRecognition();
            this.speechRecognition.continuous = true;
            this.speechRecognition.interimResults = true;
        } else {
            console.warn("Web Speech Recognition API is not supported in this browser.");
        }

        // Pre-warm and cache speech synthesis voices immediately
        this.loadVoices();
        if (typeof window !== 'undefined' && window.speechSynthesis) {
            window.speechSynthesis.onvoiceschanged = () => {
                this.loadVoices();
            };
        }

        // Get user location for GPS-based hospital requests if available
        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(
                (pos) => {
                    this.userCoords = { lat: pos.coords.latitude, lng: pos.coords.longitude };
                },
                () => {},
                { timeout: 5000 }
            );
        }
    },

    loadVoices: function() {
        if (typeof window !== 'undefined' && window.speechSynthesis) {
            this.voicesCache = window.speechSynthesis.getVoices() || [];
        }
    },

    getBestVoice: function(lang) {
        if (!this.voicesCache || this.voicesCache.length === 0) {
            this.loadVoices();
        }
        const currentLang = (lang || this.getCurrentLanguage() || 'en').toLowerCase();
        const bcp47 = (this.langCodes[currentLang] || 'en-US').toLowerCase();
        const voices = this.voicesCache;
        if (!voices || voices.length === 0) return null;

        // 1. Exact BCP47 match (e.g. kn-IN, hi-IN, en-US)
        let matched = voices.find(v => v.lang && v.lang.toLowerCase() === bcp47);
        if (matched) return matched;

        // 2. Language prefix match (e.g. kn, hi, te, ta)
        matched = voices.find(v => v.lang && v.lang.toLowerCase().startsWith(currentLang));
        if (matched) return matched;

        // 3. Name match for language
        const nameMap = {
            'kn': ['kannada', 'ಕನ್ನಡ', 'kn-in', 'sapna', 'gagan'],
            'hi': ['hindi', 'हिन्दी', 'hi-in', 'kalpana', 'hemant', 'geeta', 'swara', 'madhur'],
            'ta': ['tamil', 'தமிழ்', 'ta-in', 'valluvar', 'pallavi'],
            'te': ['telugu', 'తెలుగు', 'te-in', 'chitra', 'mohan', 'shruti'],
            'en': ['india', 'indian', 'en-in', 'google us', 'natural', 'david', 'zira', 'george', 'susan']
        };
        const keywords = nameMap[currentLang] || [];
        for (const kw of keywords) {
            matched = voices.find(v => (v.name && v.name.toLowerCase().includes(kw)) || (v.lang && v.lang.toLowerCase().includes(kw)));
            if (matched) return matched;
        }

        // 4. For non-English languages, never force an English voice, return null so browser synthesizes native regional script
        if (currentLang !== 'en') {
            return null;
        }

        // 5. English default voice
        return voices.find(v => v.lang && v.lang.toLowerCase().startsWith('en')) || voices.find(v => v.default) || voices[0] || null;
    },

    getCurrentLanguage: function() {
        if (window.LanguageManager && typeof window.LanguageManager.getLanguage === 'function') {
            const l = window.LanguageManager.getLanguage();
            if (l) return l;
        }
        try {
            const stored = localStorage.getItem("genomix_language_preference");
            if (stored) return stored;
        } catch (e) {}
        return 'en';
    },

    startListening: function(lang, onResultCallback, onErrorCallback, onEndCallback) {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            console.warn("Web Speech Recognition API is not supported in this browser.");
            if (onErrorCallback) onErrorCallback("Speech recognition not supported in browser");
            return;
        }

        // Stop any active recognition or speech first
        this.stopListening();
        this.stopSpeaking();

        try {
            const recognition = new SpeechRecognition();
            this.speechRecognition = recognition;
            const targetLang = (lang || this.getCurrentLanguage() || 'en').toLowerCase();
            const bcp47 = this.langCodes[targetLang] || 'en-US';
            recognition.lang = bcp47;
            recognition.continuous = false;
            recognition.interimResults = false;
            recognition.maxAlternatives = 1;

            recognition.onstart = () => {
                this.isListening = true;
            };

            recognition.onresult = (event) => {
                if (event.results && event.results.length > 0) {
                    const transcript = event.results[0][0].transcript;
                    if (onResultCallback) onResultCallback(transcript);
                }
            };

            recognition.onerror = (event) => {
                this.isListening = false;
                if (event.error !== 'no-speech' && onErrorCallback) {
                    onErrorCallback(event.error);
                }
            };

            recognition.onend = () => {
                this.isListening = false;
                if (onEndCallback) onEndCallback();
            };

            recognition.start();
        } catch (err) {
            console.error("Speech recognition start failed:", err);
            this.isListening = false;
            if (onErrorCallback) onErrorCallback(err.message || "Failed to start microphone");
        }
    },

    stopListening: function() {
        if (this.speechRecognition && this.isListening) {
            try { this.speechRecognition.stop(); } catch(e) {}
            this.isListening = false;
        }
    },

    speak: function(text, lang) {
        this.speakWithCallback(text, lang, null);
    },

    splitIntoFluentChunks: function(rawText) {
        if (!rawText) return [];
        let clean = String(rawText)
            .replace(/<[^>]*>/g, ' ')
            .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
            .replace(/https?:\/\/\S+/g, '')
            .replace(/[\*_#`~]/g, '')
            .replace(/\s+/g, ' ')
            .trim();

        if (!clean) return [];

        const rawSentences = clean.match(/[^.!?\n|;]+[.!?\n|;]+|[^.!?\n|;]+$/g) || [clean];
        const chunks = [];
        let currentChunk = "";

        for (let i = 0; i < rawSentences.length; i++) {
            const s = rawSentences[i].trim();
            if (!s) continue;

            if (s.length > 180) {
                const subParts = s.split(/(?<=[,،:–—])\s+/);
                for (let j = 0; j < subParts.length; j++) {
                    const sp = subParts[j].trim();
                    if (!sp) continue;
                    if ((currentChunk + " " + sp).trim().length > 180) {
                        if (currentChunk.trim()) chunks.push(currentChunk.trim());
                        currentChunk = sp;
                    } else {
                        currentChunk = (currentChunk + " " + sp).trim();
                    }
                }
            } else {
                if ((currentChunk + " " + s).trim().length > 180) {
                    if (currentChunk.trim()) chunks.push(currentChunk.trim());
                    currentChunk = s;
                } else {
                    currentChunk = (currentChunk + " " + s).trim();
                }
            }
        }

        if (currentChunk.trim()) {
            chunks.push(currentChunk.trim());
        }

        return chunks.length > 0 ? chunks : [clean];
    },
    
    speakWithCallback: function(text, lang, onEndCallback) {
        if (!this.speechSynth || !text) {
            this.isSpeaking = false;
            if (onEndCallback) onEndCallback();
            return;
        }

        // Stop any running utterance immediately before starting new one
        this.stopSpeaking();

        const currentLang = (lang || this.getCurrentLanguage() || 'en').toLowerCase();
        const bcp47 = this.langCodes[currentLang] || 'en-US';
        const matchedVoice = this.getBestVoice(currentLang);
        const chunks = this.splitIntoFluentChunks(text);

        if (!chunks || chunks.length === 0) {
            this.isSpeaking = false;
            if (onEndCallback) onEndCallback();
            return;
        }

        this.isSpeaking = true;
        let chunkIndex = 0;

        // Chrome keep-alive heartbeat to prevent silent pauses on longer passages
        clearInterval(this.keepAliveInterval);
        this.keepAliveInterval = setInterval(() => {
            if (this.speechSynth && this.speechSynth.speaking) {
                this.speechSynth.pause();
                this.speechSynth.resume();
            } else {
                clearInterval(this.keepAliveInterval);
            }
        }, 8000);

        const speakNextChunk = () => {
            if (!this.isSpeaking) return;

            if (chunkIndex >= chunks.length) {
                this.isSpeaking = false;
                clearInterval(this.keepAliveInterval);
                if (onEndCallback) onEndCallback();
                return;
            }

            const chunkText = chunks[chunkIndex].trim();
            chunkIndex++;

            if (!chunkText) {
                speakNextChunk();
                return;
            }

            const utterance = new SpeechSynthesisUtterance(chunkText);
            utterance.lang = bcp47;
            utterance.rate = 1.0;
            utterance.pitch = 1.0;
            if (matchedVoice) {
                utterance.voice = matchedVoice;
            }

            utterance.onend = () => {
                speakNextChunk();
            };

            utterance.onerror = (e) => {
                if (e.error === 'canceled' || e.error === 'interrupted') {
                    this.isSpeaking = false;
                    clearInterval(this.keepAliveInterval);
                    return;
                }
                speakNextChunk();
            };

            try {
                this.speechSynth.speak(utterance);
            } catch (err) {
                console.warn("Speech synthesis invoke error:", err);
                this.isSpeaking = false;
                clearInterval(this.keepAliveInterval);
                if (onEndCallback) onEndCallback();
            }
        };

        // Kick off immediate playback
        speakNextChunk();
    },

    stopSpeaking: function() {
        this.isSpeaking = false;
        clearInterval(this.keepAliveInterval);
        if (this.speechSynth) {
            try {
                this.speechSynth.cancel();
            } catch (e) {}
        }
    },

    // -------------------------------------------------------------
    // UNIFIED VOICE CONTROL & INTENT DISPATCHER
    // -------------------------------------------------------------

    triggerVoiceCommand: function(statusCallback) {
        if (this.isProcessingCommand) return; 
        
        const updateStatus = (state, label) => {
            if (statusCallback) statusCallback(state, label);
            this.updateVoiceStatusUI(state, label);
        };

        if (this.isListening) {
            this.stopListening();
            if (this.finalTranscript && this.finalTranscript.trim().length > 0) {
                this.isProcessingCommand = true;
                updateStatus('processing', 'Understanding...');
                this.sendVoiceCommandApi(this.finalTranscript.trim(), this.getCurrentLanguage(), updateStatus);
            } else {
                updateStatus('idle', 'Tap microphone to speak');
            }
            return;
        }

        const lang = this.getCurrentLanguage();
        this.finalTranscript = '';
        updateStatus('listening', 'How can I help you?');
        
        const greeting = window.getI18nText ? window.getI18nText('voice_greeting', 'How can I help you?') : 'How can I help you?';
        
        this.speakWithCallback(greeting, lang, () => {
            this.startListening(
                lang,
                (transcript) => {
                    // We just accumulate text. We can optionally show it to the user.
                    // For now, we update the status with a short snippet of what they are saying
                    let shortText = transcript.length > 20 ? "..." + transcript.substring(transcript.length - 20) : transcript;
                    updateStatus('listening', shortText);
                },
                (err) => {
                    this.isProcessingCommand = false;
                    updateStatus('error', 'Mic error / Not understood');
                    setTimeout(() => updateStatus('idle', 'Tap microphone to speak'), 3000);
                },
                () => {
                    if (this.isListening) {
                        this.isListening = false;
                        if (!this.isProcessingCommand) {
                            updateStatus('idle', 'Tap microphone to speak');
                        }
                    }
                }
            );
        });
    },

    sendVoiceCommandApi: function(transcript, lang, updateStatus) {
        const currentPath = window.location.pathname;

        fetch("/api/chatbot/voice-command", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                message: transcript,
                current_page: currentPath,
                language: lang,
                user_location: this.userCoords,
                pending_action: this.pendingAction
            })
        })
        .then(response => response.json())
        .then(data => {
            this.handleControlledAction(data, transcript, updateStatus);
        })
        .catch(err => {
            this.isProcessingCommand = false;
            console.error("Voice Assistant API Error:", err);
            updateStatus('error', 'Connection error. Try again.');
            this.speak("Sorry, I could not connect to the assistant server.", lang);
            setTimeout(() => updateStatus('idle', 'Tap microphone to speak'), 3000);
        });
    },

    handleControlledAction: function(data, userTranscript, updateStatus) {
        const lang = data.language || this.getCurrentLanguage();
        const action = data.action;
        const responseText = data.response || "";

        // Display user speech transcript & assistant response on screen
        if (userTranscript) {
            this.showTranscriptToast(userTranscript, responseText);
        }

        // Speak the assistant's voice response
        if (this.autoSpeakEnabled && responseText) {
            this.speak(responseText, lang);
        }

        // 1. PAGE NAVIGATION ACTION
        if (action === 'NAVIGATE' && data.navigate_url) {
            if (updateStatus) updateStatus('executing', 'Working...');
            this.pendingAction = null;
            
            setTimeout(() => {
                this.isProcessingCommand = false;
                window.location.href = data.navigate_url;
            }, 800);
            return;
        }

        // 2. THEME CONTROL ACTION
        if (action === 'CHANGE_THEME' && data.theme) {
            if (updateStatus) updateStatus('success', 'Theme updated');
            this.pendingAction = null;
            this.isProcessingCommand = false;

            if (window.ThemeManager && window.ThemeManager.setTheme) {
                window.ThemeManager.setTheme(data.theme);
            }
            setTimeout(() => { if (updateStatus) updateStatus('idle', 'Tap microphone to speak'); }, 3000);
            return;
        }

        // 3. LANGUAGE CONTROL ACTION
        if (action === 'CHANGE_LANGUAGE' && data.target_language) {
            if (updateStatus) updateStatus('success', 'Language updated');
            this.pendingAction = null;
            this.isProcessingCommand = false;

            if (window.LanguageManager && window.LanguageManager.setLanguage) {
                window.LanguageManager.setLanguage(data.target_language);
            }
            setTimeout(() => { if (updateStatus) updateStatus('idle', 'Tap microphone to speak'); }, 3000);
            return;
        }

        // 4. ANALYSIS RUN ACTION ON ACTIVE PAGE
        if (action === 'RUN_PAGE_ANALYSIS') {
            if (updateStatus) updateStatus('executing', 'Running analysis...');
            this.pendingAction = null;

            const seqInput = document.getElementById('sequence_input') || document.querySelector('textarea[name="sequence"]');
            const runBtn = document.getElementById('btn-run-complete-analysis') || document.querySelector('button[type="submit"]');
            const form = document.getElementById('complete-analysis-form') || document.querySelector('form');

            // Benchmark button fallback for quick sample loading if sequence is blank
            const benchmarkBtn = document.querySelector('button[onclick*="sequence_input"]');

            if (seqInput && seqInput.value.trim().length > 0) {
                setTimeout(() => {
                    this.isProcessingCommand = false;
                    if (runBtn) runBtn.click();
                    else if (form) form.submit();
                }, 1000);
            } else if (benchmarkBtn) {
                // Auto-load benchmark sequence and run if empty
                benchmarkBtn.click();
                setTimeout(() => {
                    this.isProcessingCommand = false;
                    if (runBtn) runBtn.click();
                    else if (form) form.submit();
                }, 1200);
            } else {
                this.isProcessingCommand = false;
                if (updateStatus) updateStatus('error', 'Please provide a DNA sequence');
                if (seqInput) seqInput.focus();
                alert("Please provide your DNA sequence or upload a sequence file to run the analysis.");
                setTimeout(() => { if (updateStatus) updateStatus('idle', 'Tap microphone to speak'); }, 3000);
            }
            return;
        }

        // 3. RECOMMENDATION / CHATBOT DISPLAY ACTION
        if (action === 'SHOW_RECOMMENDATION' || action === 'CHATBOT') {
            if (updateStatus) updateStatus('success', 'Done');
            this.pendingAction = null;
            this.isProcessingCommand = false;

            // Open global chatbot panel to render formatted response & cards
            const panel = document.getElementById('chatbot-panel');
            if (panel && panel.classList.contains('d-none')) {
                panel.classList.remove('d-none');
            }

            if (window.ChatbotUI && window.ChatbotUI.appendMessage) {
                window.ChatbotUI.appendMessage("user", userTranscript);
                window.ChatbotUI.appendMessage("assistant", responseText);
            }
            setTimeout(() => { if (updateStatus) updateStatus('idle', 'Tap microphone to speak'); }, 3000);
            return;
        }

        // 4. CONFIRMATION REQUIRED SENSITIVE ACTIONS
        if (action === 'ASK_CONFIRMATION') {
            if (updateStatus) updateStatus('processing', 'Confirmation Required');
            this.pendingAction = data.pending_action || { action: 'NAVIGATE', navigate_url: data.navigate_url };
            this.isProcessingCommand = false;

            this.showConfirmationModal(responseText, () => {
                this.confirmPendingAction(updateStatus);
            }, () => {
                this.cancelPendingAction(updateStatus);
            });
            return;
        }

        // Default Fallback
        this.isProcessingCommand = false;
        if (updateStatus) updateStatus('success', 'Done');
        setTimeout(() => { if (updateStatus) updateStatus('idle', 'Tap microphone to speak'); }, 3000);
    },

    confirmPendingAction: function(updateStatus) {
        if (!this.pendingAction) return;
        const pending = this.pendingAction;
        this.pendingAction = null;

        if (pending.navigate_url) {
            if (updateStatus) updateStatus('executing', 'Confirmed. Opening page...');
            window.location.href = pending.navigate_url;
        }
    },

    cancelPendingAction: function(updateStatus) {
        this.pendingAction = null;
        if (updateStatus) updateStatus('idle', 'Cancelled');
        this.speak("Action cancelled.", this.getCurrentLanguage());
    },

    // -------------------------------------------------------------
    // UI FEEDBACK OVERLAY, TRANSCRIPT TOAST & CONFIRMATION MODAL
    // -------------------------------------------------------------

    updateVoiceStatusUI: function(state, label) {
        const badgeLabel = document.getElementById('header-voice-label');
        const badgeIcon = document.getElementById('header-voice-icon');
        const statusText = document.getElementById('voice-status-text');

        if (badgeLabel) badgeLabel.textContent = label;
        if (statusText) statusText.textContent = label;

        if (badgeIcon) {
            if (state === 'listening') {
                badgeIcon.className = 'bi bi-mic-fill text-danger animate-pulse';
            } else if (state === 'processing') {
                badgeIcon.className = 'bi bi-arrow-repeat spin text-warning';
            } else if (state === 'executing') {
                badgeIcon.className = 'bi bi-gear-fill spin text-primary';
            } else if (state === 'success') {
                badgeIcon.className = 'bi bi-check-circle-fill text-success';
            } else if (state === 'error') {
                badgeIcon.className = 'bi bi-exclamation-triangle-fill text-danger';
            } else {
                badgeIcon.className = 'bi bi-mic-fill';
            }
        }
    },

    showTranscriptToast: function(userText, aiText) {
        if (!userText) return;
        let container = document.getElementById('voiceTranscriptContainer');
        if (!container) {
            container = document.createElement('div');
            container.id = 'voiceTranscriptContainer';
            container.className = 'position-fixed bottom-0 start-0 p-3';
            container.style.zIndex = '2200';
            container.style.pointerEvents = 'none';
            document.body.appendChild(container);
        }

        const toastId = 'toast-' + Date.now();
        const toastHtml = `
            <div id="${toastId}" class="toast show border-0 shadow-lg mb-2" role="alert" style="border-radius: 12px; background: var(--bg-card, #ffffff); border: 1px solid var(--primary, #6B46C1) !important; min-width: 280px; max-width: 380px; pointer-events: auto;">
                <div class="toast-header border-0 text-white" style="background: var(--primary, #6B46C1); border-top-left-radius: 11px; border-top-right-radius: 11px;">
                    <i class="bi bi-mic-fill me-2"></i>
                    <strong class="me-auto">Voice Assistant</strong>
                    <small>Just now</small>
                    <button type="button" class="btn-close btn-close-white" onclick="document.getElementById('${toastId}').remove();"></button>
                </div>
                <div class="toast-body p-3">
                    <div class="small text-muted mb-1"><strong>You:</strong> "${userText.replace(/"/g, '&quot;')}"</div>
                    <div class="small fw-semibold" style="color: var(--primary, #6B46C1);"><i class="bi bi-robot me-1"></i>${aiText.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</div>
                </div>
            </div>`;
        
        container.insertAdjacentHTML('beforeend', toastHtml);

        setTimeout(() => {
            const el = document.getElementById(toastId);
            if (el) el.remove();
        }, 5000);
    },

    showConfirmationModal: function(promptText, onConfirm, onCancel) {
        let modalEl = document.getElementById('voiceConfirmationModal');
        if (!modalEl) {
            const modalHtml = `
            <div class="modal fade" id="voiceConfirmationModal" tabindex="-1" aria-hidden="true" style="z-index: 2100;">
              <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content shadow-lg border-0" style="border-radius: 16px; background: var(--bg-card, #fff);">
                  <div class="modal-header border-0 pb-0">
                    <h5 class="modal-title fw-bold" style="color: var(--primary, #6B46C1);">
                      <i class="bi bi-shield-lock-fill me-2"></i>Confirmation Required
                    </h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                  </div>
                  <div class="modal-body py-3" id="voiceConfirmBody" style="color: var(--text-main, #1E293B); font-size: 0.95rem;">
                  </div>
                  <div class="modal-footer border-0 pt-0">
                    <button type="button" class="btn btn-outline-secondary px-4" id="btnVoiceCancel" data-bs-dismiss="modal">Cancel</button>
                    <button type="button" class="btn btn-primary px-4 text-white" id="btnVoiceConfirm" style="background: var(--primary, #6B46C1); border: none;">Confirm</button>
                  </div>
                </div>
              </div>
            </div>`;
            document.body.insertAdjacentHTML('beforeend', modalHtml);
            modalEl = document.getElementById('voiceConfirmationModal');
        }

        document.getElementById('voiceConfirmBody').textContent = promptText;
        const confirmBtn = document.getElementById('btnVoiceConfirm');
        const cancelBtn = document.getElementById('btnVoiceCancel');

        const bsModal = new bootstrap.Modal(modalEl);

        const handleConfirm = () => {
            bsModal.hide();
            confirmBtn.removeEventListener('click', handleConfirm);
            if (onConfirm) onConfirm();
        };

        const handleCancel = () => {
            bsModal.hide();
            cancelBtn.removeEventListener('click', handleCancel);
            if (onCancel) onCancel();
        };

        confirmBtn.onclick = handleConfirm;
        cancelBtn.onclick = handleCancel;
        bsModal.show();
    }
};

// Auto-initialize on DOM load
document.addEventListener("DOMContentLoaded", () => {
    window.VoiceAssistant.init();
});
