import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { WorkspaceAssistantPanel } from '../features/workspace/WorkspaceAssistantPanel'
import { WorkspaceEditorPanel } from '../features/workspace/WorkspaceEditorPanel'
import { WorkspaceTreePanel } from '../features/workspace/WorkspaceTreePanel'
import { fetchRun, resumeRun, streamRunEvents } from '../lib/api/runs'
import {
  appendAssistantMessage,
  createWorkspaceNode,
  fetchStoryWorkspace,
  fetchStoryWorkspaceReference,
  saveWorkspaceAssistantThread,
  saveWorkspaceNode,
  startWorkspaceRun,
  updateWorkspaceRunBridgeSeq,
} from '../lib/api/workspace'
import type { Run, StoryWorkspace, WorkspaceAssistantMessage, WorkspaceNodeType, WorkspaceReference } from '../lib/types/api'
import './pages.css'

export function StoryWorkspacePage() {
  const { storyId = '' } = useParams()
  const queryClient = useQueryClient()
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [draftContent, setDraftContent] = useState('')
  const [draftTitle, setDraftTitle] = useState('')
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [streamingAssistantText, setStreamingAssistantText] = useState('')
  const [streamingRunText, setStreamingRunText] = useState('')
  const [mode, setMode] = useState<'run' | 'workspace'>('run')
  const [referenceDraft, setReferenceDraft] = useState<WorkspaceReference>({
    premise: '',
    outline: [],
    characters: [],
    worldRules: [],
    timeline: [],
    relationshipState: [],
    foreshadowLedger: [],
  })
  const [runState, setRunState] = useState<Run | null>(null)
  const [runStreamEpoch, setRunStreamEpoch] = useState(0)
  const [isContinuingRun, setIsContinuingRun] = useState(false)
  const [isFollowingRun, setIsFollowingRun] = useState(true)
  const lastLiveRunNodeIdRef = useRef<string | null>(null)
  const latestDraftRef = useRef('')
  const latestTitleRef = useRef('')
  const latestModeRef = useRef<'run' | 'workspace'>('run')
  const latestEffectiveNodeIdRef = useRef<string | null>(null)
  const latestWorkspaceActiveNodeIdRef = useRef<string | null>(null)
  const latestRunAfterSeqRef = useRef(0)
  const latestPersistedRunAfterSeqRef = useRef(0)

  const workspaceQuery = useQuery({
    queryKey: ['story-workspace', storyId],
    queryFn: () => fetchStoryWorkspace(storyId),
    enabled: Boolean(storyId),
  })

  const referenceQuery = useQuery({
    queryKey: ['story-workspace-reference', storyId, workspaceQuery.data?.updatedAt],
    queryFn: () => fetchStoryWorkspaceReference(storyId, workspaceQuery.data),
    enabled: Boolean(storyId),
  })

  const saveMutation = useMutation({
    mutationFn: async ({ workspace, nodeId, payload }: { workspace: StoryWorkspace; nodeId: string; payload: { title?: string; content?: string } }) =>
      saveWorkspaceNode(storyId, workspace, nodeId, payload),
    onSuccess: (nextWorkspace) => {
      queryClient.setQueryData(['story-workspace', storyId], nextWorkspace)
      setSaveState('saved')
    },
    onError: () => setSaveState('error'),
  })

  const assistantMutation = useMutation({
    mutationFn: async ({ workspace, instruction }: { workspace: StoryWorkspace; instruction: string }) => {
      const text = instruction.trim()
      if (!text) {
        throw new Error('instruction is required')
      }
      const userMessage: WorkspaceAssistantMessage = {
        id: `msg-${crypto.randomUUID()}`,
        role: 'user',
        content: text,
        createdAt: new Date().toISOString(),
      }
      queryClient.setQueryData(['story-workspace', storyId], (current: StoryWorkspace | undefined) =>
        current
          ? {
              ...current,
              assistantThread: [...current.assistantThread, userMessage],
            }
          : current,
      )
      setStreamingAssistantText('')
      const response = await appendAssistantMessage(storyId, workspace, 'chat', text, (delta) => {
        setStreamingAssistantText((current) => `${current}${delta}`)
      })
      return { response, userMessage }
    },
    onSuccess: async ({ response }) => {
      setStreamingAssistantText('')
      const assistantMessage: WorkspaceAssistantMessage = {
        id: `msg-${crypto.randomUUID()}`,
        role: 'assistant',
        content: response.content,
        createdAt: new Date().toISOString(),
      }
      const currentWorkspace = queryClient.getQueryData<StoryWorkspace>(['story-workspace', storyId]) ?? workspaceQuery.data
      if (!currentWorkspace) return
      const assistantThread = [...currentWorkspace.assistantThread, assistantMessage]
      const optimisticWorkspace: StoryWorkspace = {
        ...currentWorkspace,
        assistantThread,
      }
      queryClient.setQueryData(['story-workspace', storyId], optimisticWorkspace)
      const persistedWorkspace = await saveWorkspaceAssistantThread(storyId, optimisticWorkspace, assistantThread)
      queryClient.setQueryData(['story-workspace', storyId], persistedWorkspace)
    },
    onError: () => setStreamingAssistantText(''),
  })

  const createNodeMutation = useMutation({
    mutationFn: async ({ workspace, parentId, type }: { workspace: StoryWorkspace; parentId: string | null; type: WorkspaceNodeType }) =>
      createWorkspaceNode(storyId, workspace, parentId, type),
    onSuccess: (nextWorkspace) => {
      queryClient.setQueryData(['story-workspace', storyId], nextWorkspace)
      setSelectedNodeId(nextWorkspace.activeNodeId)
      setDraftContent(nextWorkspace.activeNodeId ? nextWorkspace.contentByNodeId[nextWorkspace.activeNodeId] ?? '' : '')
    },
  })

  const runMutation = useMutation({
    mutationFn: async (prompt: string) => startWorkspaceRun(storyId, prompt, workspaceQuery.data, referenceDraft),
    onSuccess: (nextWorkspace) => {
      queryClient.setQueryData(['story-workspace', storyId], nextWorkspace)
    },
  })

  const continueMutation = useMutation({
    mutationFn: async ({ runId, payload }: { runId: string; payload: { decision?: 'continue' | 'approve' | '' } }) => resumeRun(runId, payload),
    onSuccess: async (_, variables) => {
      const runId = variables.runId
      setRunState((current) =>
        current
          ? {
              ...current,
              status: 'running',
              awaitingConfirmation: null,
            }
          : current,
      )
      setRunStreamEpoch((current) => current + 1)
      const nextRun = await fetchRun(runId)
      setRunState(nextRun)
      setIsContinuingRun(false)
      void queryClient.invalidateQueries({ queryKey: ['story-workspace', storyId] })
    },
    onError: () => {
      setIsContinuingRun(false)
    },
  })

  const workspace = workspaceQuery.data
  const liveRunNodeId = workspace?.activeNodeId ?? null
  const effectiveNodeId = mode === 'run' && isFollowingRun ? liveRunNodeId : (selectedNodeId ?? liveRunNodeId)
  const selectedNode = useMemo(() => {
    if (!workspace || !effectiveNodeId) return null
    return workspace.nodes.find((node) => node.id === effectiveNodeId) ?? null
  }, [effectiveNodeId, workspace])

  useEffect(() => {
    latestDraftRef.current = draftContent
  }, [draftContent])

  useEffect(() => {
    latestTitleRef.current = draftTitle
  }, [draftTitle])

  useEffect(() => {
    latestModeRef.current = mode
    latestEffectiveNodeIdRef.current = effectiveNodeId
    latestWorkspaceActiveNodeIdRef.current = liveRunNodeId
    latestRunAfterSeqRef.current = workspace?.runBridge?.runAfterSeq ?? 0
    latestPersistedRunAfterSeqRef.current = workspace?.runBridge?.runAfterSeq ?? 0
  }, [effectiveNodeId, liveRunNodeId, mode, workspace?.runBridge?.runAfterSeq])

  useEffect(() => {
    if (!workspace || !effectiveNodeId) return
    const activeNode = workspace.nodes.find((node) => node.id === effectiveNodeId) ?? null
    if (mode === 'run' && isFollowingRun && workspace.activeNodeId && selectedNodeId !== workspace.activeNodeId) {
      if (lastLiveRunNodeIdRef.current && lastLiveRunNodeIdRef.current !== workspace.activeNodeId) {
        setStreamingRunText('')
      }
      setSelectedNodeId(workspace.activeNodeId)
    }
    lastLiveRunNodeIdRef.current = workspace.activeNodeId ?? null
    if (!(mode === 'run' && isFollowingRun && streamingRunText)) {
      setDraftContent(workspace.contentByNodeId[effectiveNodeId] ?? '')
    }
    setDraftTitle(activeNode?.title ?? '')
  }, [effectiveNodeId, isFollowingRun, mode, selectedNodeId, streamingRunText, workspace])

  useEffect(() => {
    if (!referenceQuery.data) return
    setReferenceDraft(referenceQuery.data)
  }, [referenceQuery.data])

  useEffect(() => {
    if (!workspace || !effectiveNodeId || mode === 'run') return
    const currentNode = workspace.nodes.find((node) => node.id === effectiveNodeId) ?? null
    const currentContent = workspace.contentByNodeId[effectiveNodeId] ?? ''
    const currentTitle = currentNode?.title ?? ''
    if (draftContent === currentContent && draftTitle === currentTitle) return

    setSaveState('saving')
    const timer = window.setTimeout(() => {
      const payload: { title?: string; content?: string } = {}
      if (draftTitle !== currentTitle) {
        payload.title = latestTitleRef.current
      }
      if (draftContent !== currentContent) {
        payload.content = latestDraftRef.current
      }
      void saveMutation.mutate({ workspace, nodeId: effectiveNodeId, payload })
    }, 500)

    return () => window.clearTimeout(timer)
  }, [draftContent, draftTitle, effectiveNodeId, mode, saveMutation, workspace])

  useEffect(() => {
    const runId = workspace?.runBridge?.activeRunId
    if (!runId) return

    let cancelled = false
    void fetchRun(runId).then((run) => {
      if (!cancelled) {
        setRunState(run)
      }
    })

    const initialAfterSeq = latestRunAfterSeqRef.current || workspace?.runBridge?.runAfterSeq || 0
    void streamRunEvents(runId, initialAfterSeq, async (event) => {
      if (cancelled) return
      latestRunAfterSeqRef.current = event.seq
      queryClient.setQueryData(['story-workspace', storyId], (current: StoryWorkspace | undefined) =>
        current
          ? {
              ...current,
              runBridge: current.runBridge
                ? {
                    ...current.runBridge,
                    runAfterSeq: Math.max(current.runBridge.runAfterSeq ?? 0, event.seq),
                  }
                : current.runBridge,
            }
          : current,
      )
      if (workspace?.runBridge?.activeRunId && event.seq - latestPersistedRunAfterSeqRef.current >= 20) {
        latestPersistedRunAfterSeqRef.current = event.seq
        void updateWorkspaceRunBridgeSeq(storyId, workspace.runBridge.activeRunId, event.seq)
      }
      if (event.type === 'stream.clear') {
        setStreamingRunText('')
        setSaveState('idle')
      }
      const streamChannel = typeof event.payload.channel === 'string' ? event.payload.channel : ''
      const isRunContentChunk = event.type === 'stream.chunk' && event.payload.delta && (event.category === 'content' || streamChannel === 'content')
      if (isRunContentChunk && latestModeRef.current === 'run' && latestEffectiveNodeIdRef.current === latestWorkspaceActiveNodeIdRef.current && latestWorkspaceActiveNodeIdRef.current) {
        setStreamingRunText((current) => {
          const next = `${current}${event.payload.delta ?? ''}`
          setDraftContent(next)
          return next
        })
      }
      if (event.payload.awaiting_confirmation) {
        setRunState((current) =>
          current
            ? {
                ...current,
                awaitingConfirmation: event.payload.awaiting_confirmation,
                status: 'waiting_input',
              }
            : current,
        )
      }
      if (event.type === 'ui.event' && event.category === 'TOOL') {
        void queryClient.invalidateQueries({ queryKey: ['story-workspace', storyId] })
      }
      if (event.type === 'ui.event' && event.payload.event === 'run.awaiting_confirmation') {
        const latestRun = await fetchRun(runId)
        if (!cancelled) {
          setRunState(latestRun)
        }
        void queryClient.invalidateQueries({ queryKey: ['story-workspace', storyId] })
      }
    }).catch(() => {})

    return () => {
      cancelled = true
    }
  }, [runStreamEpoch, storyId, workspace?.runBridge?.activeRunId])

  if (workspaceQuery.isLoading) {
    return <div className='panel page-empty'>正在加载作品工作台...</div>
  }

  if (workspaceQuery.isError || !workspace) {
    return <div className='panel page-empty'>作品工作台加载失败，请确认故事数据是否可用。</div>
  }

  return (
    <section className='workspace-page'>
      <WorkspaceTreePanel
        workspace={workspace}
        activeNodeId={effectiveNodeId}
        onSelect={(nodeId) => {
          const node = workspace.nodes.find((item) => item.id === nodeId) ?? null
          setSelectedNodeId(nodeId)
          setDraftContent(workspace.contentByNodeId[nodeId] ?? '')
          setDraftTitle(node?.title ?? '')
          if (mode === 'run') {
            setIsFollowingRun(false)
          } else {
            setMode('workspace')
          }
        }}
        onCreateNode={(parentId, type) => {
          createNodeMutation.mutate({ workspace, parentId, type })
        }}
      />

      <div className='workspace-page__center'>
        <WorkspaceEditorPanel
          workspace={workspace}
          selectedNode={selectedNode}
          title={draftTitle}
          content={draftContent}
          saveState={saveState}
          autoFollow={mode === 'run' && isFollowingRun && (Boolean(streamingRunText) || isContinuingRun)}
          liveRunChapterLabel={liveRunNodeId ? workspace.nodes.find((node) => node.id === liveRunNodeId)?.title ?? null : null}
          detachedFromRun={mode === 'run' && !isFollowingRun && Boolean(liveRunNodeId)}
          onReturnToLiveRun={() => {
            if (!liveRunNodeId) return
            setIsFollowingRun(true)
            setSelectedNodeId(liveRunNodeId)
            setDraftContent(workspace.contentByNodeId[liveRunNodeId] ?? '')
            const liveNode = workspace.nodes.find((node) => node.id === liveRunNodeId) ?? null
            setDraftTitle(liveNode?.title ?? '')
          }}
          onTitleChange={(value) => {
            setDraftTitle(value)
            setSaveState('idle')
          }}
          onContentChange={(value) => {
            setDraftContent(value)
            setSaveState('idle')
          }}
        />
      </div>

      <WorkspaceAssistantPanel
        workspace={workspace}
        selectedNodeId={selectedNodeId}
        isPending={assistantMutation.isPending || runMutation.isPending || continueMutation.isPending}
        streamingText={streamingAssistantText}
        awaitingConfirmation={runState?.awaitingConfirmation ?? null}
        runStatus={runState?.status ?? workspace.runBridge?.runSyncStatus ?? null}
        isContinuingRun={isContinuingRun}
        onSubmit={async (instruction) => {
          await assistantMutation.mutateAsync({ workspace, instruction })
        }}
        onContinueRun={async () => {
          const shouldResumeRun = Boolean(
            workspace.runBridge?.activeRunId && (runState?.awaitingConfirmation || runState?.status === 'waiting_input' || runState?.status === 'idle'),
          )
          if (workspace.runBridge?.activeRunId && shouldResumeRun) {
            setMode('run')
            setIsFollowingRun(true)
            setIsContinuingRun(true)
            setStreamingRunText('')
            if (runState?.awaitingConfirmation) {
              await continueMutation.mutateAsync({ runId: workspace.runBridge.activeRunId, payload: { decision: 'continue' } })
            } else {
              await continueMutation.mutateAsync({ runId: workspace.runBridge.activeRunId, payload: {} })
            }
          } else {
            setIsFollowingRun(true)
            setMode('run')
            setStreamingRunText('')
            await runMutation.mutateAsync(referenceDraft.premise || workspace.premise)
          }
        }}
      />
    </section>
  )
}
