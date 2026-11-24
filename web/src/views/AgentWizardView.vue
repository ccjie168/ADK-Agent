<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { apiFetch, getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";
import PageHeader from "../components/PageHeader.vue";

interface TemplateParameter {
  name: string;
  description: string;
  required: boolean;
  default: unknown;
}

interface TemplateInfo {
  template_id: string;
  description: string;
  parameters: TemplateParameter[];
  tools: string[];
}

interface TemplatesResponse {
  configured: boolean;
  templates: TemplateInfo[];
}

interface PreviewResult {
  manifest: Record<string, unknown>;
  agent_py: string;
  artifact_digest: string;
  size: number;
}

interface ComposeResult {
  tenant: string;
  id: string;
  version: string;
  digest: string;
  artifact_digest: string;
}

const LIMITS = {
  name: 64,
  version: 256,
  tenant: 256,
  owner: 2000,
  description: 2000,
  instruction: 4000,
  lists: 16,
} as const;

const DATA_CLASSES = ["public", "internal", "confidential", "restricted"] as const;

const COMPOSE_ERRORS: Record<string, string> = {
  compose_invalid: "参数不合法，请检查名称、版本、指令与工具",
  tenant_forbidden: "不能发布到其他租户",
  compose_not_configured: "控制台未启用一键发布，请使用 CLI",
  registry_not_configured: "注册表未配置",
  registry_conflict: "该版本已存在且内容不同，请换一个版本号",
  artifact_store_unavailable: "工件存储不可用",
  registry_unavailable: "注册表不可用，请稍后重试",
  forbidden: "当前角色没有此操作权限",
};

const auth = useAuthStore();
const templates = ref<TemplateInfo[]>([]);
const selectedId = ref("");
const configured = ref(false);
const step = ref(1);
const loading = ref(false);
const message = ref("");
const error = ref("");
const previewResult = ref<PreviewResult | null>(null);
const composeResult = ref<ComposeResult | null>(null);

const form = reactive({
  name: "",
  version: "1.0.0",
  tenant: "",
  owner: "",
  description: "",
  instruction: "",
  tools: [] as string[],
  dataClasses: [] as string[],
});

const canPreview = computed(() => auth.hasCapability("registry.publish"));
const canPublish = computed(() => auth.hasCapability("registry.compose"));
const denied = computed(() => !canPreview.value && !canPublish.value);
const selected = computed(
  () => templates.value.find((item) => item.template_id === selectedId.value) ?? null,
);

const validation = computed(() => {
  const problems: string[] = [];
  if (!form.name) problems.push("名称必填");
  else if (form.name.length > LIMITS.name) problems.push(`名称最多 ${LIMITS.name} 字符`);
  if (!form.version) problems.push("版本必填");
  else if (form.version.length > LIMITS.version) problems.push(`版本最多 ${LIMITS.version} 字符`);
  if (!form.tenant) problems.push("租户必填");
  else if (form.tenant.length > LIMITS.tenant) problems.push(`租户最多 ${LIMITS.tenant} 字符`);
  if (form.owner.length > LIMITS.owner) problems.push(`所有者最多 ${LIMITS.owner} 字符`);
  if (form.description.length > LIMITS.description) {
    problems.push(`描述最多 ${LIMITS.description} 字符`);
  }
  if (!form.instruction) problems.push("指令必填");
  else if (form.instruction.length > LIMITS.instruction) {
    problems.push(`指令最多 ${LIMITS.instruction} 字符`);
  }
  if (form.tools.length > LIMITS.lists || form.dataClasses.length > LIMITS.lists) {
    problems.push(`工具与数据分级最多各 ${LIMITS.lists} 项`);
  }
  return problems;
});

const cliCommand = computed(() => {
  const parts = [
    "adk-agent compose",
    `--template ${selectedId.value || "single-llm"}`,
    `--tenant ${form.tenant || "TENANT"}`,
    `--id ${form.name || "AGENT_ID"}`,
    `--version ${form.version || "1.0.0"}`,
    '--instruction "<system instruction>"',
  ];
  if (form.tools.length) parts.push(`--tools ${form.tools.join(",")}`);
  if (form.dataClasses.length) parts.push(`--data-classes ${form.dataClasses.join(",")}`);
  parts.push("--key FILE --key-id ID --builder-key FILE --builder-key-id ID");
  parts.push("--artifact-dir DIR");
  return parts.join(" ");
});

const manifestText = computed(() =>
  previewResult.value ? JSON.stringify(previewResult.value.manifest, null, 2) : "",
);

onMounted(async () => {
  form.tenant = auth.principal?.tenant ?? "";
  if (!canPreview.value) return;
  try {
    const body = await getJson<TemplatesResponse>("/api/compose/templates");
    templates.value = body.templates ?? [];
    configured.value = Boolean(body.configured);
    if (templates.value.length) selectedId.value = templates.value[0].template_id;
  } catch {
    error.value = "模板不可用";
  }
});

function toggleTool(tool: string) {
  const index = form.tools.indexOf(tool);
  if (index >= 0) form.tools.splice(index, 1);
  else form.tools.push(tool);
}

function toggleClass(name: string) {
  const index = form.dataClasses.indexOf(name);
  if (index >= 0) form.dataClasses.splice(index, 1);
  else form.dataClasses.push(name);
}

function payload(): Record<string, unknown> {
  const body: Record<string, unknown> = {
    template_id: selectedId.value,
    name: form.name,
    version: form.version,
    tenant: form.tenant,
    instruction: form.instruction,
    tools: form.tools,
    data_classes: form.dataClasses,
  };
  if (form.owner) body.owner = form.owner;
  if (form.description) body.description = form.description;
  return body;
}

async function errorCode(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { error?: string };
    return body.error ?? "";
  } catch {
    return "";
  }
}

function showError(code: string) {
  error.value = COMPOSE_ERRORS[code] ?? "请求失败";
}

async function preview() {
  error.value = "";
  message.value = "";
  if (validation.value.length) {
    error.value = validation.value[0];
    return;
  }
  loading.value = true;
  try {
    const response = await apiFetch("/api/compose/preview", {
      method: "POST",
      body: JSON.stringify(payload()),
    });
    if (!response.ok) {
      showError(await errorCode(response));
      return;
    }
    previewResult.value = (await response.json()) as PreviewResult;
    step.value = 3;
  } catch {
    error.value = "请求失败: 网络错误";
  } finally {
    loading.value = false;
  }
}

async function publish() {
  error.value = "";
  message.value = "";
  if (validation.value.length) {
    error.value = validation.value[0];
    return;
  }
  loading.value = true;
  try {
    const response = await apiFetch("/api/compose", {
      method: "POST",
      body: JSON.stringify(payload()),
    });
    if (!response.ok) {
      showError(await errorCode(response));
      return;
    }
    composeResult.value = (await response.json()) as ComposeResult;
    message.value = `已发布 ${composeResult.value.id}@${composeResult.value.version}`;
    step.value = 4;
  } catch {
    error.value = "请求失败: 网络错误";
  } finally {
    loading.value = false;
  }
}

async function copyCommand() {
  try {
    await navigator.clipboard.writeText(cliCommand.value);
    message.value = "命令已复制";
  } catch {
    message.value = "复制失败，请手动选择命令";
  }
}
</script>

<template>
  <PageHeader title="新建 Agent" description="用模板生成、预览并一键发布" />

  <div v-if="denied" class="card">
    <p>无访问权限：需要 registry.publish 或 registry.compose。</p>
  </div>

  <template v-else>
    <p v-if="!configured" class="notice">
      <strong>控制台未启用一键发布，请使用 CLI。</strong>
      预览仍可用；发布需要运维配置四个 compose 密钥参数。
    </p>

    <div class="wizard-steps">
      <span :class="['wizard-step', { active: step === 1 }]">1 模板</span>
      <span :class="['wizard-step', { active: step === 2 }]">2 参数</span>
      <span :class="['wizard-step', { active: step === 3 }]">3 预览</span>
      <span :class="['wizard-step', { active: step === 4 }]">4 发布</span>
    </div>

    <p v-if="error" class="form-error">{{ error }}</p>
    <p v-if="message" class="form-ok">{{ message }}</p>

    <section v-show="step === 1" class="card">
      <h2>选择模板</h2>
      <p v-if="!templates.length" class="muted">没有可用模板。</p>
      <label v-for="template in templates" :key="template.template_id" class="wizard-option">
        <input v-model="selectedId" type="radio" :value="template.template_id" />
        <span>
          <strong>{{ template.template_id }}</strong>
          <span class="muted">{{ template.description }}</span>
        </span>
      </label>
      <button class="primary" :disabled="!selectedId" @click="step = 2">下一步</button>
    </section>

    <section v-show="step === 2" class="card">
      <h2>填写参数</h2>
      <div class="form-grid">
        <label>名称<input v-model="form.name" placeholder="support_bot" /></label>
        <label>版本<input v-model="form.version" placeholder="1.0.0" /></label>
        <label>租户<input v-model="form.tenant" placeholder="team-a" /></label>
        <label>所有者<input v-model="form.owner" placeholder="可选" /></label>
        <label class="wide">描述<input v-model="form.description" placeholder="可选" /></label>
        <label class="wide">
          指令
          <textarea v-model="form.instruction" rows="6" placeholder="You are helpful."></textarea>
        </label>
      </div>
      <fieldset v-if="selected?.tools.length" class="wizard-fieldset">
        <legend>工具</legend>
        <label v-for="tool in selected.tools" :key="tool" class="checkbox">
          <input
            type="checkbox"
            :checked="form.tools.includes(tool)"
            @change="toggleTool(tool)"
          />
          {{ tool }}
        </label>
      </fieldset>
      <fieldset class="wizard-fieldset">
        <legend>数据分级（授予工具时使用）</legend>
        <label v-for="name in DATA_CLASSES" :key="name" class="checkbox">
          <input
            type="checkbox"
            :checked="form.dataClasses.includes(name)"
            @change="toggleClass(name)"
          />
          {{ name }}
        </label>
      </fieldset>
      <p v-if="validation.length" class="form-error">{{ validation[0] }}</p>
      <div class="wizard-actions">
        <button @click="step = 1">上一步</button>
        <button class="primary" :disabled="!canPreview || validation.length > 0 || loading" @click="preview">
          预览
        </button>
      </div>
    </section>

    <section v-show="step === 3 && previewResult" class="card">
      <h2>预览</h2>
      <p class="muted">
        工件 digest <code>{{ previewResult?.artifact_digest }}</code>
        （{{ previewResult?.size }} 字节）
      </p>
      <h3>manifest.json</h3>
      <pre class="code-block">{{ manifestText }}</pre>
      <h3>agent.py</h3>
      <pre class="code-block">{{ previewResult?.agent_py }}</pre>
      <div class="wizard-actions">
        <button @click="step = 2">上一步</button>
        <button
          v-if="canPublish"
          class="primary"
          :disabled="!configured || loading"
          @click="publish"
        >
          发布
        </button>
        <span v-else class="muted">当前角色没有 registry.compose，不能发布。</span>
      </div>
      <p v-if="canPublish && !configured" class="muted">
        未配置发布密钥，发布按钮不可用。可复制下面的 CLI 命令：
      </p>
      <div v-if="canPublish && !configured" class="cli-hint">
        <pre class="code-block">{{ cliCommand }}</pre>
        <button @click="copyCommand">复制命令</button>
      </div>
    </section>

    <section v-show="step === 4 && composeResult" class="card">
      <h2>已发布</h2>
      <p>
        {{ composeResult?.tenant }}/{{ composeResult?.id }}@{{ composeResult?.version }}
        已签名发布。
      </p>
      <p class="muted">
        版本 digest <code>{{ composeResult?.digest }}</code>，工件
        <code>{{ composeResult?.artifact_digest }}</code>
      </p>
      <div class="wizard-actions">
        <router-link class="btn" to="/registry">去注册表</router-link>
        <button @click="step = 2">再发布一个版本</button>
      </div>
    </section>
  </template>
</template>
