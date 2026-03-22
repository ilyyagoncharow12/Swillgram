const socket = io();

let currentChat = { type: null, id: null };
let localStream, remoteStream, peerConnection;
const servers = { iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] };

// --- Подключение к комнате для получения сообщений ---
function joinChatRoom(chatType, chatId) {
    if (currentChat.id !== null) {
        socket.emit('leave', { room: `${currentChat.type}_${currentChat.id}` });
    }
    currentChat = { type: chatType, id: chatId };
    socket.emit('join', { room: `${chatType}_${chatId}` });
    // Загрузить историю сообщений (можно реализовать отдельный эндпоинт)
}

// --- Отправка текстового сообщения ---
function sendMessage() {
    const input = document.getElementById('message-input');
    const content = input.value.trim();
    if (content === '') return;
    const msg = {
        content: content,
        type: 'text'
    };
    if (currentChat.type === 'user') {
        msg.recipient_id = currentChat.id;
    } else if (currentChat.type === 'group') {
        msg.group_id = currentChat.id;
    }
    socket.emit('send_message', msg);
    input.value = '';
}

// --- Получение нового сообщения ---
socket.on('new_message', (data) => {
    if ((currentChat.type === 'user' && data.recipient_id === currentChat.id) ||
        (currentChat.type === 'group' && data.group_id === currentChat.id)) {
        appendMessage(data);
    }
});

function appendMessage(msg) {
    const messagesDiv = document.getElementById('messages');
    const el = document.createElement('div');
    el.className = 'message';
    el.innerHTML = `<strong>${msg.sender}</strong>: ${msg.content} <span class="time">${new Date(msg.timestamp).toLocaleTimeString()}</span>`;
    messagesDiv.appendChild(el);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

// --- Голосовые сообщения (запись через MediaRecorder) ---
let mediaRecorder;
let audioChunks = [];
async function startVoiceRecording() {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(stream);
    audioChunks = [];
    mediaRecorder.ondataavailable = event => audioChunks.push(event.data);
    mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
        const reader = new FileReader();
        reader.readAsDataURL(audioBlob);
        reader.onloadend = () => {
            const base64data = reader.result;
            const msg = {
                content: base64data,
                type: 'voice'
            };
            if (currentChat.type === 'user') {
                msg.recipient_id = currentChat.id;
            } else {
                msg.group_id = currentChat.id;
            }
            socket.emit('send_message', msg);
        };
    };
    mediaRecorder.start();
    setTimeout(() => mediaRecorder.stop(), 5000); // 5 секунд записи
}

// --- WebRTC звонки ---
async function startCall() {
    // Запрашиваем доступ к аудио
    localStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    setupPeerConnection();
    const offer = await peerConnection.createOffer();
    await peerConnection.setLocalDescription(offer);
    socket.emit('call_user', { target_id: currentChat.id, offer: peerConnection.localDescription });
}

async function startVideoCall() {
    localStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
    setupPeerConnection();
    const offer = await peerConnection.createOffer();
    await peerConnection.setLocalDescription(offer);
    socket.emit('call_user', { target_id: currentChat.id, offer: peerConnection.localDescription });
}

function setupPeerConnection() {
    peerConnection = new RTCPeerConnection(servers);
    peerConnection.onicecandidate = event => {
        if (event.candidate) {
            socket.emit('ice_candidate', { target_id: currentChat.id, candidate: event.candidate });
        }
    };
    peerConnection.ontrack = event => {
        const remoteVideo = document.createElement('video');
        remoteVideo.srcObject = event.streams[0];
        remoteVideo.autoplay = true;
        document.body.appendChild(remoteVideo); // или в модальное окно
    };
    localStream.getTracks().forEach(track => peerConnection.addTrack(track, localStream));
}

socket.on('incoming_call', async (data) => {
    if (confirm(`Входящий звонок от ${data.caller_name}. Принять?`)) {
        // Создаём peer connection для ответа
        localStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
        setupPeerConnection();
        await peerConnection.setRemoteDescription(new RTCSessionDescription(data.offer));
        const answer = await peerConnection.createAnswer();
        await peerConnection.setLocalDescription(answer);
        socket.emit('call_answer', { caller_id: data.caller_id, answer: peerConnection.localDescription });
    } else {
        // отказ
    }
});

socket.on('call_answered', async (data) => {
    await peerConnection.setRemoteDescription(new RTCSessionDescription(data.answer));
});

socket.on('ice_candidate', async (data) => {
    if (peerConnection) {
        await peerConnection.addIceCandidate(new RTCIceCandidate(data.candidate));
    }
});

// --- Функции для групп и профиля ---
function showCreateGroupModal() {
    document.getElementById('group-modal').style.display = 'block';
}
function closeModal() {
    document.getElementById('group-modal').style.display = 'none';
}