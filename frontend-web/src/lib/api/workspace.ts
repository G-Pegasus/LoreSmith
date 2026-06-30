import { ApiError, apiFetch } from './client'
import { pythonCreateRun, pythonFetch, pythonStream } from './pythonClient'
import { fetchStories } from './stories'
import type {
  ArcPlan,
  ArcSummary,
  CharacterSnapshot,
  StoryCharacter,
  StoryWordCount,
  StoryCompass,
  StoryReferenceDetail,
  StoryWorkspace,
  WorkspaceAssistantMessage,
  VolumePlan,
  VolumeSummary,
  WorkspaceAssistantStreamResponse,
  WorkspaceCharacterItem,
  WorkspaceForeshadowItem,
  WorkspaceNodeType,
  WorkspaceOutlineItem,
  WorkspaceReference,
  WorkspaceRelationshipItem,
  WorkspaceTimelineItem,
  WorkspaceWorldRuleItem,
} from '../types/api'
import {
  createWorkspaceFromStory,
  createWorkspaceNodeLocal,
  loadWorkspaceLocal,
  saveWorkspaceLocal,
  updateWorkspaceNodeLocal,
} from './workspaceLocal'

function isWorkspaceFallbackError(error: unknown) {
  return error instanceof ApiError && [404, 405, 501].includes(error.status)
}

function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : []
}

function normalizeReferencePayload(payload: Record<string, unknown> | WorkspaceReference | null | undefined): WorkspaceReference {
  const source = (payload ?? {}) as Record<string, unknown>
  return {
    premise: typeof source.premise === 'string' ? source.premise : '',
    outline: asArray<WorkspaceOutlineItem>(source.outline),
    characters: asArray<WorkspaceCharacterItem>(source.characters),
    worldRules: Array.isArray(source.worldRules)
      ? (source.worldRules as WorkspaceWorldRuleItem[])
      : Array.isArray(source.world_rules)
        ? (source.world_rules as WorkspaceWorldRuleItem[])
        : [],
    timeline: asArray<WorkspaceTimelineItem>(source.timeline),
    relationshipState: Array.isArray(source.relationshipState)
      ? (source.relationshipState as WorkspaceRelationshipItem[])
      : Array.isArray(source.relationship_state)
        ? (source.relationship_state as WorkspaceRelationshipItem[])
        : [],
    foreshadowLedger: Array.isArray(source.foreshadowLedger)
      ? (source.foreshadowLedger as WorkspaceForeshadowItem[])
      : Array.isArray(source.foreshadow_ledger)
        ? (source.foreshadow_ledger as WorkspaceForeshadowItem[])
        : [],
  }
}

function normalizeCompass(value: unknown): StoryCompass {
  const source = (value ?? {}) as Record<string, unknown>
  return {
    endingDirection: typeof source.endingDirection === 'string' ? source.endingDirection : typeof source.ending_direction === 'string' ? String(source.ending_direction) : '',
    openThreads: Array.isArray(source.openThreads) ? (source.openThreads as string[]) : Array.isArray(source.open_threads) ? (source.open_threads as string[]) : [],
    estimatedScale: typeof source.estimatedScale === 'string' ? source.estimatedScale : typeof source.estimated_scale === 'string' ? String(source.estimated_scale) : '',
    lastUpdated: typeof source.lastUpdated === 'number' ? source.lastUpdated : typeof source.last_updated === 'number' ? source.last_updated : 0,
  }
}

function normalizeArcPlan(value: unknown): ArcPlan {
  const source = (value ?? {}) as Record<string, unknown>
  return {
    index: typeof source.index === 'number' ? source.index : undefined,
    title: typeof source.title === 'string' ? source.title : '',
    goal: typeof source.goal === 'string' ? source.goal : '',
    estimatedChapters:
      typeof source.estimatedChapters === 'number'
        ? source.estimatedChapters
        : typeof source.estimated_chapters === 'number'
          ? source.estimated_chapters
          : 0,
    chapters: asArray<WorkspaceOutlineItem>(source.chapters),
  }
}

function normalizeVolumePlan(value: unknown): VolumePlan {
  const source = (value ?? {}) as Record<string, unknown>
  return {
    index: typeof source.index === 'number' ? source.index : undefined,
    title: typeof source.title === 'string' ? source.title : '',
    theme: typeof source.theme === 'string' ? source.theme : '',
    final: Boolean(source.final),
    arcs: asArray<unknown>(source.arcs).map(normalizeArcPlan),
  }
}

function normalizeCharacterSnapshot(value: unknown): CharacterSnapshot {
  const source = (value ?? {}) as Record<string, unknown>
  return {
    volume: typeof source.volume === 'number' ? source.volume : 0,
    arc: typeof source.arc === 'number' ? source.arc : 0,
    name: typeof source.name === 'string' ? source.name : '',
    status: typeof source.status === 'string' ? source.status : '',
    power: typeof source.power === 'string' ? source.power : '',
    motivation: typeof source.motivation === 'string' ? source.motivation : '',
    relations: typeof source.relations === 'string' ? source.relations : '',
  }
}

function normalizeArcSummary(value: unknown): ArcSummary {
  const source = (value ?? {}) as Record<string, unknown>
  return {
    volume: typeof source.volume === 'number' ? source.volume : 0,
    arc: typeof source.arc === 'number' ? source.arc : 0,
    title: typeof source.title === 'string' ? source.title : '',
    summary: typeof source.summary === 'string' ? source.summary : '',
    keyEvents: Array.isArray(source.keyEvents) ? (source.keyEvents as string[]) : Array.isArray(source.key_events) ? (source.key_events as string[]) : [],
  }
}

function normalizeVolumeSummary(value: unknown): VolumeSummary {
  const source = (value ?? {}) as Record<string, unknown>
  return {
    volume: typeof source.volume === 'number' ? source.volume : 0,
    title: typeof source.title === 'string' ? source.title : '',
    summary: typeof source.summary === 'string' ? source.summary : '',
    keyEvents: Array.isArray(source.keyEvents) ? (source.keyEvents as string[]) : Array.isArray(source.key_events) ? (source.key_events as string[]) : [],
  }
}

function normalizeReferenceDetailPayload(payload: Record<string, unknown> | StoryReferenceDetail | null | undefined): StoryReferenceDetail {
  const source = (payload ?? {}) as Record<string, unknown>
  return {
    storyId: typeof source.storyId === 'string' ? source.storyId : typeof source.story_id === 'string' ? String(source.story_id) : '',
    title: typeof source.title === 'string' ? source.title : '',
    premise: typeof source.premise === 'string' ? source.premise : '',
    outline: asArray<WorkspaceOutlineItem>(source.outline),
    layeredOutline: Array.isArray(source.layeredOutline)
      ? (source.layeredOutline as VolumePlan[])
      : asArray<unknown>(source.layered_outline).map(normalizeVolumePlan),
    compass: normalizeCompass(source.compass),
    characters: asArray<WorkspaceCharacterItem>(source.characters),
    characterSnapshots: Array.isArray(source.characterSnapshots)
      ? (source.characterSnapshots as CharacterSnapshot[])
      : asArray<unknown>(source.character_snapshots).map(normalizeCharacterSnapshot),
    worldRules: Array.isArray(source.worldRules)
      ? (source.worldRules as WorkspaceWorldRuleItem[])
      : Array.isArray(source.world_rules)
        ? (source.world_rules as WorkspaceWorldRuleItem[])
        : [],
    timeline: asArray<WorkspaceTimelineItem>(source.timeline),
    relationshipState: Array.isArray(source.relationshipState)
      ? (source.relationshipState as WorkspaceRelationshipItem[])
      : Array.isArray(source.relationship_state)
        ? (source.relationship_state as WorkspaceRelationshipItem[])
        : [],
    foreshadowLedger: Array.isArray(source.foreshadowLedger)
      ? (source.foreshadowLedger as WorkspaceForeshadowItem[])
      : Array.isArray(source.foreshadow_ledger)
        ? (source.foreshadow_ledger as WorkspaceForeshadowItem[])
        : [],
    arcSummaries: Array.isArray(source.arcSummaries)
      ? (source.arcSummaries as ArcSummary[])
      : asArray<unknown>(source.arc_summaries).map(normalizeArcSummary),
    volumeSummaries: Array.isArray(source.volumeSummaries)
      ? (source.volumeSummaries as VolumeSummary[])
      : asArray<unknown>(source.volume_summaries).map(normalizeVolumeSummary),
    progress: {
      completedChapters:
        typeof (source.progress as Record<string, unknown> | undefined)?.completedChapters === 'number'
          ? Number((source.progress as Record<string, unknown>).completedChapters)
          : typeof (source.progress as Record<string, unknown> | undefined)?.completed_chapters === 'number'
            ? Number((source.progress as Record<string, unknown>).completed_chapters)
            : 0,
      currentChapter:
        typeof (source.progress as Record<string, unknown> | undefined)?.currentChapter === 'number'
          ? Number((source.progress as Record<string, unknown>).currentChapter)
          : typeof (source.progress as Record<string, unknown> | undefined)?.current_chapter === 'number'
            ? Number((source.progress as Record<string, unknown>).current_chapter)
            : 0,
      totalWordCount:
        typeof (source.progress as Record<string, unknown> | undefined)?.totalWordCount === 'number'
          ? Number((source.progress as Record<string, unknown>).totalWordCount)
          : typeof (source.progress as Record<string, unknown> | undefined)?.total_word_count === 'number'
            ? Number((source.progress as Record<string, unknown>).total_word_count)
            : 0,
      currentVolume:
        typeof (source.progress as Record<string, unknown> | undefined)?.currentVolume === 'number'
          ? Number((source.progress as Record<string, unknown>).currentVolume)
          : typeof (source.progress as Record<string, unknown> | undefined)?.current_volume === 'number'
            ? Number((source.progress as Record<string, unknown>).current_volume)
            : 0,
    },
  }
}

function serializeReferencePayload(reference: WorkspaceReference) {
  return {
    premise: reference.premise,
    outline: reference.outline,
    characters: reference.characters,
    world_rules: reference.worldRules,
    timeline: reference.timeline,
    relationship_state: reference.relationshipState,
    foreshadow_ledger: reference.foreshadowLedger,
  }
}

function normalizeStoryCharacters(reference?: WorkspaceReference): StoryCharacter[] {
  return (reference?.characters ?? [])
    .map((item) => ({
      name: String(item.name ?? '').trim(),
      role: String(item.role ?? '').trim(),
      description: String(item.description ?? item.summary ?? '').trim(),
    }))
    .filter((item) => item.name)
}

async function loadStoryOrThrow(storyId: string) {
  const stories = await fetchStories()
  const story = stories.find((item) => item.storyId === storyId)
  if (!story) {
    throw new Error('作品不存在')
  }
  return story
}

export async function fetchStoryWorkspace(storyId: string) {
  try {
    return await pythonFetch<StoryWorkspace>(`/internal/v1/workspace?story_id=${encodeURIComponent(storyId)}`)
  } catch (error) {
    if (!isWorkspaceFallbackError(error)) {
      throw error
    }

    const local = loadWorkspaceLocal(storyId)
    if (local) {
      return local
    }

    const story = await loadStoryOrThrow(storyId)
    return saveWorkspaceLocal(createWorkspaceFromStory(story))
  }
}

export async function fetchStoryWorkspaceReference(storyId: string, workspace?: StoryWorkspace) {
  try {
    const payload = await pythonFetch<Record<string, unknown>>(`/internal/v1/workspace/reference-snapshot?story_id=${encodeURIComponent(storyId)}`)
    return normalizeReferencePayload(payload)
  } catch (error) {
    if (!isWorkspaceFallbackError(error)) {
      throw error
    }
    return {
      premise: workspace?.premise ?? '',
      outline: [],
      characters: [],
      worldRules: [],
      timeline: [],
      relationshipState: [],
      foreshadowLedger: [],
    } satisfies WorkspaceReference
  }
}

export async function fetchStoryReferenceDetail(storyId: string, workspace?: StoryWorkspace) {
  try {
    const payload = await pythonFetch<Record<string, unknown>>(`/internal/v1/workspace/reference-detail?story_id=${encodeURIComponent(storyId)}`)
    return normalizeReferenceDetailPayload(payload)
  } catch (error) {
    if (!isWorkspaceFallbackError(error)) {
      throw error
    }
    return {
      storyId,
      title: workspace?.title ?? '',
      premise: workspace?.premise ?? '',
      outline: [],
      layeredOutline: [],
      compass: { openThreads: [] },
      characters: [],
      characterSnapshots: [],
      worldRules: [],
      timeline: [],
      relationshipState: [],
      foreshadowLedger: [],
      arcSummaries: [],
      volumeSummaries: [],
      progress: {
        completedChapters: 0,
        currentChapter: 0,
        totalWordCount: 0,
        currentVolume: 0,
      },
    } satisfies StoryReferenceDetail
  }
}

export async function saveWorkspaceNode(
  storyId: string,
  workspace: StoryWorkspace,
  nodeId: string,
  payload: { title?: string; summary?: string; content?: string },
) {
  try {
    return await pythonFetch<StoryWorkspace>(`/internal/v1/workspace/nodes/${encodeURIComponent(nodeId)}?story_id=${encodeURIComponent(storyId)}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    })
  } catch (error) {
    if (!isWorkspaceFallbackError(error)) {
      throw error
    }
    return updateWorkspaceNodeLocal(workspace, nodeId, payload)
  }
}

export async function createWorkspaceNode(storyId: string, workspace: StoryWorkspace, parentId: string | null, type: WorkspaceNodeType) {
  try {
    return await pythonFetch<StoryWorkspace>(`/internal/v1/workspace/nodes?story_id=${encodeURIComponent(storyId)}`, {
      method: 'POST',
      body: JSON.stringify({ parentId, type }),
    })
  } catch (error) {
    if (!isWorkspaceFallbackError(error)) {
      throw error
    }
    return createWorkspaceNodeLocal(workspace, parentId, type)
  }
}

export async function appendAssistantMessage(
  storyId: string,
  workspace: StoryWorkspace,
  action: string,
  instruction: string,
  onDelta?: (delta: string) => void,
) {
  void workspace
  const response = await pythonStream(`/internal/v1/workspace/intent/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      intent_type: 'assistant_reply',
      story: {
        story_id: storyId,
        title: workspace.title,
        premise: workspace.premise,
      },
      node: {
        node_id: workspace.activeNodeId ?? '',
        type: 'chapter',
        title: workspace.nodes.find((item) => item.id === workspace.activeNodeId)?.title ?? '',
        summary: '',
        chapter: 0,
        asset_type: 'chapter',
      },
      content: workspace.activeNodeId ? workspace.contentByNodeId[workspace.activeNodeId] ?? '' : '',
      action,
      instruction,
      label: '',
      payload: {},
      metadata: {
        workspace_id: storyId,
        tenant_id: 'workspace-agent',
        user_id: 'assistant-reply',
      },
    }),
  })

  if (!response.ok) {
    const text = await response.text()
    let json: { code?: string; message?: string } | null = null
    try {
      json = text ? (JSON.parse(text) as { code?: string; message?: string }) : null
    } catch {
      json = null
    }
    throw new ApiError(json?.message ?? '请求失败', json?.code ?? 'HTTP_ERROR', response.status)
  }

  if (!response.body) {
    throw new ApiError('流式响应为空', 'EMPTY_STREAM', response.status)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let donePayload: WorkspaceAssistantStreamResponse | null = null

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })

    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''

    for (const frame of frames) {
      const lines = frame.split('\n')
      const event = lines.find((line) => line.startsWith('event:'))?.slice(6).trim()
      const data = lines
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trim())
        .join('\n')
      if (!event || !data) {
        continue
      }
      const payload = JSON.parse(data) as { delta?: string } | WorkspaceAssistantStreamResponse
      if (event === 'delta' && 'delta' in payload && payload.delta) {
        onDelta?.(payload.delta)
      }
      if (event === 'done') {
        donePayload = payload as WorkspaceAssistantStreamResponse
      }
    }

    if (done) {
      break
    }
  }

  if (!donePayload) {
    throw new ApiError('流式响应未结束', 'INCOMPLETE_STREAM', response.status)
  }

  const content = donePayload.content ?? donePayload.result?.content ?? ''
  return {
    ...donePayload,
    content,
    fallbackUsed: donePayload.fallbackUsed ?? Boolean(donePayload.fallback_used),
  } satisfies WorkspaceAssistantStreamResponse
}

export async function saveWorkspaceAssistantThread(storyId: string, workspace: StoryWorkspace, assistantThread: WorkspaceAssistantMessage[]) {
  try {
    return await pythonFetch<StoryWorkspace>(`/internal/v1/workspace/assistant-thread?story_id=${encodeURIComponent(storyId)}`, {
      method: 'PUT',
      body: JSON.stringify({ assistantThread }),
    })
  } catch (error) {
    if (!isWorkspaceFallbackError(error)) {
      throw error
    }
    return saveWorkspaceLocal({
      ...workspace,
      assistantThread,
    })
  }
}

function normalizeRunWordCount(wordCount?: StoryWordCount | null) {
  const minWords = Math.max(2000, Number(wordCount?.minWords ?? 2000) || 2000)
  const targetWords = Math.max(minWords, Number(wordCount?.targetWords ?? 2500) || 2500)
  return {
    min_words: minWords,
    target_words: targetWords,
  }
}

export async function startWorkspaceRun(
  storyId: string,
  prompt: string,
  workspace?: StoryWorkspace,
  reference?: WorkspaceReference,
  wordCount?: StoryWordCount | null,
) {
  const reusableRunStatuses = new Set(['running', 'waiting_input'])
  const existingRunId = workspace?.runBridge?.activeRunId ?? ''
  const existingRunStatus = workspace?.runBridge?.runSyncStatus ?? ''
  const runId = existingRunId && reusableRunStatuses.has(existingRunStatus) ? existingRunId : crypto.randomUUID()
  const storyTitle = workspace?.title ?? storyId
  const storyPremise = reference?.premise || workspace?.premise || prompt
  await pythonCreateRun({
    run_id: runId,
    story: {
      story_id: storyId,
      title: storyTitle,
      premise: storyPremise,
      characters: normalizeStoryCharacters(reference),
      word_count: normalizeRunWordCount(wordCount),
    },
    execution: {
      provider: 'deepseek',
      model: 'deepseek-v4-pro',
      context_window: 128000,
    },
    input: {
      mode: 'start',
      prompt,
    },
    storage: {
      kind: 'local',
      base_path: `output/workspace/${storyId}`,
    },
    metadata: {
      workspace_id: storyId,
      tenant_id: 'workspace-agent',
      user_id: 'run-start',
      extra: reference
        ? {
            reference_snapshot: serializeReferencePayload(reference),
          }
        : {},
    },
    config_path: 'dev_config.json',
  })
  if (reference) {
    await updateWorkspaceReference(storyId, reference)
  }

  return pythonFetch<StoryWorkspace>(`/internal/v1/workspace/run-bridge?story_id=${encodeURIComponent(storyId)}`, {
    method: 'PUT',
    body: JSON.stringify({
      activeRunId: runId,
      runAfterSeq: runId === existingRunId ? workspace?.runBridge?.runAfterSeq ?? 0 : 0,
      runSyncStatus: 'running',
      runSyncUpdatedAt: new Date().toISOString(),
      lastCompletedChapter: runId === existingRunId ? workspace?.runBridge?.lastCompletedChapter ?? null : null,
    }),
  })
}

export async function updateWorkspaceReference(storyId: string, reference: WorkspaceReference) {
  const payload = await pythonFetch<Record<string, unknown>>(`/internal/v1/workspace/reference-snapshot?story_id=${encodeURIComponent(storyId)}`, {
    method: 'PUT',
    body: JSON.stringify(serializeReferencePayload(reference)),
  })
  return normalizeReferencePayload(payload)
}

export async function updateWorkspaceRunBridgeSeq(storyId: string, runId: string, runAfterSeq: number) {
  return pythonFetch<StoryWorkspace>(`/internal/v1/workspace/run-bridge?story_id=${encodeURIComponent(storyId)}`, {
    method: 'PUT',
    body: JSON.stringify({
      activeRunId: runId,
      runAfterSeq,
      runSyncStatus: 'running',
      runSyncUpdatedAt: new Date().toISOString(),
      lastCompletedChapter: null,
    }),
  })
}
