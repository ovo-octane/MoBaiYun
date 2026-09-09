(function () {

  "use strict";



  var socket = io();



  // DOM 元素

  var historyEl = document.getElementById("history");

  var messageInput = document.getElementById("message-input");

  var sendBtn = document.getElementById("send-btn");

  var roleSelect = document.getElementById("role-select");

  var aiSelect = document.getElementById("ai-select");

  var rolePanel = document.getElementById("role-panel");

  var addRoleModal = document.getElementById("addRoleModal");

  var editRoleModal = document.getElementById("editRoleModal");

  var saveRoleBtn = document.getElementById("save-role-btn");

  var updateRoleBtn = document.getElementById("update-role-btn");

  var roleNameInput = document.getElementById("role-name");

  var rolePromptInput = document.getElementById("role-prompt");

  var editRoleNameInput = document.getElementById("edit-role-name");

  var editRolePromptInput = document.getElementById("edit-role-prompt");



  // TTS 元素

  var ttsEnable = document.getElementById("tts-enable");

  var ttsLanguage = document.getElementById("tts-language");

  var ttsVoice = document.getElementById("tts-voice");

  var ttsStyle = document.getElementById("tts-style");

  var ttsRole = document.getElementById("tts-role");

  var ttsRate = document.getElementById("tts-rate");

  var ttsRateValue = document.getElementById("tts-rate-value");

  var ttsPitch = document.getElementById("tts-pitch");



  var currentEditRoleName = "";



  // ================================================================

  // 显示名称

  // ================================================================



  function getDisplayName(role) {

    if (role === "user") return "我";

    if (role === "assistant") {

      var roleName = roleSelect ? roleSelect.value : "";

      return roleName || "助手";

    }

    return "系统";

  }





  // ================================================================

  // 工具函数

  // ================================================================



  function escapeHtml(text) {

    var div = document.createElement("div");

    div.textContent = text;

    return div.innerHTML;

  }



  function renderMarkdown(text) {

    return text

      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")

      .replace(/\*(.+?)\*/g, "<em>$1</em>")

      .replace(/`([^`]+)`/g, "<code>$1</code>")

      .replace(/\n/g, "<br>");

  }



  function appendMessage(role, content, audioUrl) {

    var badgeClass = role === "user" ? "bg-primary" : role === "assistant" ? "bg-success" : "bg-secondary";

    var badgeText = getDisplayName(role);

    var item = document.createElement("div");

    item.className = "mb-2 message-item";

    item.setAttribute("data-role", role);

    item.innerHTML =

      '<span class="badge ' + badgeClass + ' message-header" data-role="' + role + '">' + escapeHtml(badgeText) + "</span>" +

      '<div class="mt-1 text-break">' + renderMarkdown(content) + "</div>";

    if (audioUrl && role === "assistant") {

      var audio = document.createElement("audio");

      audio.controls = true;

      audio.className = "mt-1";

      audio.preload = "metadata";

      audio.src = audioUrl;

      item.querySelector(".text-break").after(audio);

    }

    historyEl.appendChild(item);

    historyEl.scrollTop = historyEl.scrollHeight;

  }



  // ================================================================

  // 角色管理

  // ================================================================



  function updateRolePanel(roles) {

    rolePanel.innerHTML = "";

    Object.keys(roles).forEach(function (name) {

      var prompt = roles[name];

      var div = document.createElement("div");

      div.className = "d-flex justify-content-between align-items-start mb-2 p-2";

      div.style.background = "rgba(37,37,37,0.5)";

      div.style.borderRadius = "var(--radius-sm)";

      div.innerHTML =

        '<div style="flex:1;min-width:0;">' +

        '<strong>' + escapeHtml(name) + '</strong>' +

        '<div style="font-size:12px;color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + escapeHtml(prompt || "无提示词") + "</div>" +

        "</div>" +

        '<div class="d-flex gap-1 ms-2" style="flex-shrink:0;">' +

        '<button class="btn btn-sm btn-outline-warning edit-role" data-role-name="' + encodeURIComponent(name) + '" data-prompt="' + encodeURIComponent(prompt || "") + '">编辑</button>' +

        '<button class="btn btn-sm btn-outline-danger delete-role" data-role-name="' + encodeURIComponent(name) + '">删除</button>' +

        "</div>";

      rolePanel.appendChild(div);

    });

  }



  function updateRoleSelect(roles) {

    var current = roleSelect.value;

    roleSelect.innerHTML = '';

    Object.keys(roles).forEach(function (name) {

      var opt = document.createElement("option");

      opt.value = name;

      opt.textContent = name;

      if (name === current) opt.selected = true;

      roleSelect.appendChild(opt);

    });

    // 同步移动端

    var mobileSelect = document.getElementById("mobile-role-select");

    if (mobileSelect) {

      mobileSelect.innerHTML = roleSelect.innerHTML;

      if (current) mobileSelect.value = current;

    }

  }



  function addRole(roleName, prompt) {

    fetch("/add_role", {

      method: "POST",

      headers: { "Content-Type": "application/json" },

      body: JSON.stringify({ role_name: roleName, prompt: prompt }),

    })

      .then(function (res) { return res.json(); })

      .then(function (data) {

        if (data && data.ok) {

          refreshRoleList();

          var modal = bootstrap.Modal.getInstance(addRoleModal);

          if (modal) modal.hide();

          roleNameInput.value = "";

          rolePromptInput.value = "";

        } else {

          alert(data && data.error ? data.error : "添加角色失败");

        }

      })

      .catch(function (err) {

        alert("请求失败: " + err.message);

      });

  }



  function editRole(roleName, newPrompt) {

    fetch("/edit_role", {

      method: "POST",

      headers: { "Content-Type": "application/json" },

      body: JSON.stringify({ role_name: roleName, new_prompt: newPrompt }),

    })

      .then(function (res) { return res.json(); })

      .then(function (data) {

        if (data && data.ok) {

          refreshRoleList();

          var modal = bootstrap.Modal.getInstance(editRoleModal);

          if (modal) modal.hide();

        } else {

          alert(data && data.error ? data.error : "编辑角色失败");

        }

      })

      .catch(function (err) {

        alert("请求失败: " + err.message);

      });

  }



  function deleteRole(roleName) {

    if (!confirm("确定删除角色「" + roleName + "」？相关对话历史也会被删除。")) return;

    fetch("/delete_role", {

      method: "POST",

      headers: { "Content-Type": "application/json" },

      body: JSON.stringify({ role_name: roleName }),

    })

      .then(function (res) { return res.json(); })

      .then(function (result) {

        if (result && result.ok) {

          refreshRoleList();

          if (roleSelect.value === roleName) {

            roleSelect.value = "";

            socket.emit("switch_role", { role: "" });

          }

        } else {

          alert(result && result.error ? result.error : "删除失败");

        }

      })

      .catch(function (err) {

        alert("请求失败: " + err.message);

      });

  }



  function refreshRoleList() {

    fetch("/get_roles")

      .then(function (res) { return res.json(); })

      .then(function (data) {

        if (data && data.roles) {

          updateRolePanel(data.roles);

          updateRoleSelect(data.roles);

        }

      });

  }



  // ================================================================

  // Azure TTS 语音数据

  // ================================================================



  var azureVoices = {

    "zh-CN": [

      { name: "晓晓 (女声)", value: "zh-CN-XiaoxiaoNeural" },

      { name: "云希 (男声)", value: "zh-CN-YunxiNeural" },

      { name: "云健 (男声)", value: "zh-CN-YunjianNeural" },

      { name: "晓伊 (女声)", value: "zh-CN-XiaoyiNeural" },

      { name: "云阳 (男声)", value: "zh-CN-YunyangNeural" },

      { name: "晓辰 (女声)", value: "zh-CN-XiaochenNeural" },

      { name: "晓涵 (女声)", value: "zh-CN-XiaohanNeural" },

      { name: "晓梦 (女声)", value: "zh-CN-XiaomengNeural" },

      { name: "晓墨 (女声)", value: "zh-CN-XiaomoNeural" },

      { name: "晓秋 (女声)", value: "zh-CN-XiaoqiuNeural" },

      { name: "晓柔 (女声)", value: "zh-CN-XiaorouNeural" },

      { name: "晓瑞 (女声)", value: "zh-CN-XiaoruiNeural" },

      { name: "晓双 (女童声)", value: "zh-CN-XiaoshuangNeural" },

      { name: "晓妍 (女声)", value: "zh-CN-XiaoyanNeural" },

      { name: "晓雨 (女声)", value: "zh-CN-XiaoyuNeural" },

      { name: "晓珍 (女声)", value: "zh-CN-XiaozhenNeural" },

      { name: "云帆 (男声)", value: "zh-CN-YunfanNeural" },

      { name: "云峰 (男声)", value: "zh-CN-YunfengNeural" },

      { name: "云浩 (男声)", value: "zh-CN-YunhaoNeural" },

      { name: "云杰 (男声)", value: "zh-CN-YunjieNeural" },

      { name: "云霞 (男声)", value: "zh-CN-YunxiaNeural" },

      { name: "云霄 (男声)", value: "zh-CN-YunxiaoNeural" },

      { name: "云野 (男声)", value: "zh-CN-YunyeNeural" },

      { name: "云逸 (男声)", value: "zh-CN-YunyiNeural" },

      { name: "云泽 (男声)", value: "zh-CN-YunzeNeural" },

    ],

    "zh-CN-sichuan": [{ name: "四川云希 (男声)", value: "zh-CN-sichuan-YunxiNeural" }],

    "zh-CN-shandong": [{ name: "山东云祥 (男声)", value: "zh-CN-shandong-YunxiangNeural" }],

    "zh-CN-henan": [{ name: "河南云登 (男声)", value: "zh-CN-henan-YundengNeural" }],

    "zh-CN-liaoning": [

      { name: "辽宁晓北 (女声)", value: "zh-CN-liaoning-XiaobeiNeural" },

      { name: "辽宁云彪 (男声)", value: "zh-CN-liaoning-YunbiaoNeural" },

    ],

    "zh-CN-shaanxi": [{ name: "陕西晓妮 (女声)", value: "zh-CN-shaanxi-XiaoniNeural" }],

    "zh-CN-guangxi": [{ name: "广西云奇 (男声)", value: "zh-CN-guangxi-YunqiNeural" }],

    "zh-TW": [

      { name: "晓珍 (女声)", value: "zh-TW-HsiaoChenNeural" },

      { name: "晓雨 (女声)", value: "zh-TW-HsiaoYuNeural" },

      { name: "云哲 (男声)", value: "zh-TW-YunJheNeural" },

    ],

    "zh-HK": [

      { name: "晓曼 (女声)", value: "zh-HK-HiuMaanNeural" },

      { name: "晓佳 (女声)", value: "zh-HK-HiuGaaiNeural" },

      { name: "云龙 (男声)", value: "zh-HK-WanLungNeural" },

    ],

  };



  function updateVoiceOptions() {

    if (!ttsLanguage || !ttsVoice) return;

    var lang = ttsLanguage.value;

    var voices = azureVoices[lang] || [];

    var currentVal = ttsVoice.value;

    ttsVoice.innerHTML = "";

    voices.forEach(function (v) {

      var opt = document.createElement("option");

      opt.value = v.value;

      opt.textContent = v.name;

      if (v.value === currentVal) opt.selected = true;

      ttsVoice.appendChild(opt);

    });

    if (voices.length > 0 && !voices.some(function (v) { return v.value === ttsVoice.value; })) {

      ttsVoice.value = voices[0].value;

    }

  }



  function getTtsOptions() {

    return {

      enable: ttsEnable ? ttsEnable.checked : true,

      locale: ttsLanguage ? ttsLanguage.value : "zh-CN",

      voice: ttsVoice ? ttsVoice.value : "zh-CN-XiaoxiaoNeural",

      style: ttsStyle ? ttsStyle.value : "",

      role: ttsRole ? ttsRole.value : "",

      rate: ttsRate ? parseFloat(ttsRate.value) : 1.0,

      pitch: ttsPitch ? ttsPitch.value : "default",

    };

  }



  function saveTtsSettings() {

    var settings = getTtsOptions();

    localStorage.setItem("mobaiyun_tts", JSON.stringify(settings));

  }



  function loadTtsSettings() {

    var raw = localStorage.getItem("mobaiyun_tts");

    if (!raw) return;

    try {

      var s = JSON.parse(raw);

      if (ttsEnable) ttsEnable.checked = s.enable !== false;

      if (s.locale && ttsLanguage) ttsLanguage.value = s.locale;

      if (s.voice && ttsVoice) ttsVoice.value = s.voice;

      if (s.style && ttsStyle) ttsStyle.value = s.style;

      if (s.role && ttsRole) ttsRole.value = s.role;

      if (s.rate && ttsRate) ttsRate.value = s.rate;

      if (s.pitch && ttsPitch) ttsPitch.value = s.pitch;

    } catch (e) {}

  }



  // ================================================================

  // SocketIO 事件

  // ================================================================



  socket.on("connect", function () {

    console.log("Socket connected");

    if (typeof window.initialRoles !== "undefined") {

      var roleNames = Object.keys(window.initialRoles);

      if (roleNames.length === 1) {

        var roleName = roleNames[0];

        if (roleSelect.value !== roleName) {

          roleSelect.value = roleName;

        }

        socket.emit("switch_role", { role: roleName });

      }

    }

  });



  socket.on("receive_message", function (data) {

    var response = data && data.response ? data.response : "";

    var audioUrl = data && data.audio_url ? data.audio_url : null;

    appendMessage("assistant", response, audioUrl);

    if (audioUrl) {

      var audio = new Audio(audioUrl);

      audio.play().catch(function () {});

    }

  });



  socket.on("update_history", function (data) {

    historyEl.innerHTML = "";

    if (Array.isArray(data && data.history)) {

      data.history.forEach(function (msg) {

        appendMessage(msg.role, msg.content, msg.audio_url);

      });

    }

    if (data && data.ai && aiSelect.value !== data.ai) {

      aiSelect.value = data.ai;

    }

  });



  socket.on("switch_role_error", function (data) {

    alert(data && data.error ? data.error : "角色切换失败");

  });



  // ================================================================

  // 按钮和输入事件

  // ================================================================



  sendBtn.addEventListener("click", function () {

    var message = (messageInput.value || "").trim();

    if (!message) return;

    var role = (roleSelect.value || "").trim();

    if (!role) {

      alert("请先选择一个角色");

      roleSelect.focus();

      return;

    }

    socket.emit("send_message", {

      message: message,

      role: role,

      ai: "deepseek",

      tts_options: getTtsOptions(),

    });

    appendMessage("user", message);

    messageInput.value = "";

    saveTtsSettings();

  });



  messageInput.addEventListener("keydown", function (e) {

    if (e.key === "Enter" && !e.shiftKey) {

      e.preventDefault();

      sendBtn.click();

    }

  });



  saveRoleBtn.addEventListener("click", function () {

    var name = (roleNameInput.value || "").trim();

    var prompt = (rolePromptInput.value || "").trim();

    if (!name) { alert("角色名称不能为空"); return; }

    addRole(name, prompt);

  });



  updateRoleBtn.addEventListener("click", function () {

    if (!currentEditRoleName) return;

    editRole(currentEditRoleName, (editRolePromptInput.value || "").trim());

  });



  rolePanel.addEventListener("click", function (e) {

    var target = e.target;

    if (target.classList.contains("delete-role")) {

      var n = decodeURIComponent(target.getAttribute("data-role-name") || ""); if (n) deleteRole(n);

    } else if (target.classList.contains("edit-role")) {

      var n = decodeURIComponent(target.getAttribute("data-role-name") || ""); var p = decodeURIComponent(target.getAttribute("data-prompt") || "");

      if (n && p !== null) {

        currentEditRoleName = n;

        editRoleNameInput.value = n;

        editRolePromptInput.value = p;

        var modal = new bootstrap.Modal(editRoleModal);

        modal.show();

      }

    }

  });



  roleSelect.addEventListener("change", function () {

    var role = (roleSelect.value || "").trim();

    var mobileSelect = document.getElementById("mobile-role-select");

    if (mobileSelect) mobileSelect.value = role;

    socket.emit("switch_role", { role: role });

  });



  // 移动端角色选择器同步

  var mobileRoleSelect = document.getElementById("mobile-role-select");

  if (mobileRoleSelect) {

    mobileRoleSelect.addEventListener("change", function () {

      var role = (mobileRoleSelect.value || "").trim();

      if (roleSelect) roleSelect.value = role;

      socket.emit("switch_role", { role: role });

    });

  }



  // ================================================================

  // TTS 事件

  // ================================================================



  if (ttsRate) ttsRate.addEventListener("input", function () {

    if (ttsRateValue) ttsRateValue.textContent = this.value;

    saveTtsSettings();

  });

  if (ttsLanguage) ttsLanguage.addEventListener("change", function () { updateVoiceOptions(); saveTtsSettings(); });

  if (ttsEnable) ttsEnable.addEventListener("change", saveTtsSettings);

  if (ttsVoice) ttsVoice.addEventListener("change", saveTtsSettings);

  if (ttsStyle) ttsStyle.addEventListener("change", saveTtsSettings);

  if (ttsRole) ttsRole.addEventListener("change", saveTtsSettings);

  if (ttsPitch) ttsPitch.addEventListener("change", saveTtsSettings);



  // ================================================================

  // 初始化

  // ================================================================



  loadTtsSettings();

  updateVoiceOptions();

  if (ttsRate && ttsRateValue) ttsRateValue.textContent = ttsRate.value;





  if (typeof window.initialRoles !== "undefined") {

    updateRolePanel(window.initialRoles);

    updateRoleSelect(window.initialRoles);

  }

})();





