<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { apiFetch, getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";

interface AgentInfo {
  name: string;
  description: string;
}

interface LogLine {
  who: "you" | "agent" | "system";
  text: string;
}

interface SseEvent {
  name: string;
  data: Record<string, unknown>;
}

const auth = useAuthStore();
const agents = ref<AgentInfo[]>([]);
const selectedAgent = ref("");
const message = ref("");
const log = ref<LogLine[]>([]);
const denied = computed(() => !auth.hasCapability("chat.run"));

function parseEvent(block: string): SseEvent {
  const out: SseEvent = { name: "", data: {} };
  for (const line of block.split("\n")) {
    if (line.startsWith("event: ")) out.name = line.slice(7);
    else if (line.startsWith("data: ")) out.data = JSON.parse(line.slice(6)) as Record<string, unknown>;
  }
  return out;
}

async function send() {
  const text = message.value.trim();
  if (!text || !selectedAgent.value) return;
  message.value = "";
  log.value.push({ who: "you", text });

  const response = await apiFetch("/api/chat/stream", {
    method: "POST",
    body: JSON.stringify({ agent: selectedAgent.value, message: text }),
  });
  if (!response.ok) {
    const data = (await response.json()) as { error?: string };
    log.value.push({ who: "system", text: data.error ?? `error ${response.status}` });
    return;
  }

  const reader = response.body?.getReader();
  if (!reader) return;
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let index: number;
    while ((index = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      const event = parseEvent(block);
      if (event.name === "done") {
        const reply = String((event.data as { reply?: string }).reply ?? "(empty)");
        log.value.push({ who: "agent", text: reply });
      } else if (event.name === "error") {
        const err = String((event.data as { error?: string }).error ?? "agent run failed");
        log.value.push({ who: "system", text: err });
      }
    }
  }
}

onMounted(async () => {
  if (denied.value) return;
  try {
    agents.value = await getJson<AgentInfo[]>("/api/agents");
    if (agents.value.length) selectedAgent.value = agents.value[0].name;
  } catch {
    agents.value = [];
  }
});
</script>

<template>
  <div class="panel">
    <h1>聊天</h1>
    <p v-if="denied" class="placeholder">无访问权限</p>
    <template v-else>
      <div class="chat-log">
        <div v-for="(line, index) in log" :key="index" :class="['chat-line', line.who]">
          <span class="chat-who">{{ line.who }}</span>
          <span>{{ line.text }}</span>
        </div>
        <p v-if="log.length === 0" class="placeholder">开始对话…</p>
      </div>
      <div class="row">
        <select v-model="selectedAgent">
          <option v-for="agent in agents" :key="agent.name" :value="agent.name">
            {{ agent.name }}
          </option>
        </select>
        <input v-model="message" class="grow" placeholder="输入消息…" autocomplete="off" />
        <button class="primary" @click="send">发送</button>
      </div>
    </template>
  </div>
</template>
