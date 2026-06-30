export type ApiEnvelope<T> = {
  code: string
  message: string
  data: T
}

export type StoryCharacter = {
  name: string
  role?: string | null
  description?: string | null
}

export type StoryWordCount = {
  minWords: number
  targetWords: number
  maxWords?: number
}

export type Story = {
  storyId: string
  title: string
  premise: string
  genre?: string | null
  style: string | null
  characters?: StoryCharacter[]
  wordCount?: StoryWordCount | null
  latestRunId: string | null
  createdAt: string | null
}

export type StoryListResponse = {
  items: Story[]
}

export type CreateStoryRequest = {
  storyId: string
  runId: string
  title: string
  premise: string
  characters?: StoryCharacter[]
  wordCount?: Omit<StoryWordCount, 'maxWords'>
  prompt: string
  provider?: string
  model?: string
  outputPath?: string
  configPath?: string
}

export type CreateStoryResponse = {
  storyId: string
  runId: string
  status: string
  kernelStatus: string
}

export type InspirationMessage = {
  messageId: string
  role: 'user' | 'assistant' | 'system'
  content: string
  createdAt: string
}

export type InspirationSession = {
  sessionId: string
  memorySummary: string
  messages: InspirationMessage[]
  updatedAt: string
}

export type AwaitingConfirmation = {
  pauseAfterChapter: number
  nextChapter: number
  completedCount: number
  status?: string | null
}

export type Run = {
  runId: string
  storyId: string
  status: string
  kernelStatus: string
  phase: string | null
  flow: string | null
  provider: string | null
  model: string | null
  currentChapter: number | null
  completedCount: number | null
  totalWordCount: number | null
  awaitingConfirmation?: AwaitingConfirmation | null
}

export type RunListResponse = {
  items: Run[]
}

export type RunEventsResponse = {
  run_id: string
  after_seq: number
  limit: number
  returned_count: number
  total_available: number
  next_after_seq: number
  has_more: boolean
  items: Array<Record<string, unknown>>
}

export type RunEventPayload = Record<string, unknown> & {
  summary?: string
  delta?: string
  level?: string
  event?: string
  awaiting_confirmation?: AwaitingConfirmation
}

export type RunEvent = {
  eventId: string
  seq: number
  type: string
  category: string
  time: string
  payload: RunEventPayload
}

export type RunEventStreamHandler = (event: RunEvent) => void

export type ChapterResponse = {
  run_id: string
  chapter: Record<string, unknown>
}

export type Artifact = {
  artifactId: string
  type: string
  name: string
  chapter: number | null
  mimeType: string | null
  uri: string
  createdAt: string | null
}

export type ArtifactListResponse = {
  items: Artifact[]
}

export type ResumeRunRequest = {
  prompt?: string
  decision?: 'continue' | 'approve' | ''
  feedback?: string
}

export type RunInstructionRequest = {
  type: string
  text?: string
  decision?: 'continue' | 'approve' | ''
  feedback?: string
}

export type RunAck = {
  run_id: string
  status: string
  kernel_status?: string | null
  accepted?: boolean | null
}

export type WorkspaceNodeType = 'volume' | 'chapter'

export type WorkspaceNode = {
  id: string
  parentId: string | null
  type: WorkspaceNodeType
  title: string
  order: number
  summary?: string
}

export type WorkspaceAssistantMessage = {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  createdAt: string
}

export type WorkspaceAssistantStreamResponse = {
  storyId?: string
  messageId?: string
  content: string
  fallbackUsed: boolean
  result?: {
    content?: string
  }
  fallback_used?: boolean
}

export type WorkspaceRunBridge = {
  activeRunId: string | null
  runAfterSeq: number
  runSyncStatus: 'idle' | 'running' | 'waiting_input' | 'completed' | 'failed' | 'canceled'
  runSyncUpdatedAt: string | null
  lastCompletedChapter?: string | null
}

export type StoryWorkspace = {
  storyId: string
  title: string
  premise: string
  style: string | null
  updatedAt: string | null
  localOnly?: boolean
  nodes: WorkspaceNode[]
  activeNodeId: string | null
  contentByNodeId: Record<string, string>
  assistantThread: WorkspaceAssistantMessage[]
  runBridge?: WorkspaceRunBridge
}

export type WorkspaceOutlineItem = {
  chapter?: number
  title?: string
  core_event?: string
  hook?: string
  scenes?: string[]
}

export type WorkspaceCharacterItem = {
  name?: string
  aliases?: string[]
  role?: string | null
  description?: string | null
  summary?: string | null
  arc?: string
  traits?: string[]
  tier?: string
}

export type WorkspaceWorldRuleItem = {
  category?: string
  rule?: string
  boundary?: string
}

export type WorkspaceTimelineItem = {
  chapter?: number
  time?: string
  event?: string
  characters?: string[]
}

export type WorkspaceRelationshipItem = {
  character_a?: string
  character_b?: string
  relation?: string
  chapter?: number
}

export type WorkspaceForeshadowItem = {
  id?: string
  description?: string
  planted_at?: number
  status?: string
  resolved_at?: number
}

export type WorkspaceReference = {
  premise: string
  outline: WorkspaceOutlineItem[]
  characters: WorkspaceCharacterItem[]
  worldRules: WorkspaceWorldRuleItem[]
  timeline: WorkspaceTimelineItem[]
  relationshipState: WorkspaceRelationshipItem[]
  foreshadowLedger: WorkspaceForeshadowItem[]
}

export type StoryCompass = {
  endingDirection?: string
  openThreads: string[]
  estimatedScale?: string
  lastUpdated?: number
}

export type ArcPlan = {
  index?: number
  title?: string
  goal?: string
  estimatedChapters?: number
  chapters: WorkspaceOutlineItem[]
}

export type VolumePlan = {
  index?: number
  title?: string
  theme?: string
  final?: boolean
  arcs: ArcPlan[]
}

export type CharacterSnapshot = {
  volume?: number
  arc?: number
  name?: string
  status?: string
  power?: string
  motivation?: string
  relations?: string
}

export type ArcSummary = {
  volume?: number
  arc?: number
  title?: string
  summary?: string
  keyEvents: string[]
}

export type VolumeSummary = {
  volume?: number
  title?: string
  summary?: string
  keyEvents: string[]
}

export type StoryReferenceDetail = {
  storyId: string
  title: string
  premise: string
  outline: WorkspaceOutlineItem[]
  layeredOutline: VolumePlan[]
  compass: StoryCompass
  characters: WorkspaceCharacterItem[]
  characterSnapshots: CharacterSnapshot[]
  worldRules: WorkspaceWorldRuleItem[]
  timeline: WorkspaceTimelineItem[]
  relationshipState: WorkspaceRelationshipItem[]
  foreshadowLedger: WorkspaceForeshadowItem[]
  arcSummaries: ArcSummary[]
  volumeSummaries: VolumeSummary[]
  progress: {
    completedChapters: number
    currentChapter: number
    totalWordCount: number
    currentVolume: number
  }
}
