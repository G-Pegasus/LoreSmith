import { useMemo } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { InspirationChatPanel } from '../features/stories/InspirationChatPanel'
import { StoryCreateForm } from '../features/stories/StoryCreateForm'
import { createStory } from '../lib/api/stories'
import { startWorkspaceRun } from '../lib/api/workspace'
import type { CreateStoryRequest } from '../lib/types/api'
import './pages.css'

export function NewStoryPage() {
  const navigate = useNavigate()
  const inspirationSessionId = useMemo(() => {
    const storageKey = 'ainovel:new-story-inspiration-session'
    if (typeof window === 'undefined') {
      return crypto.randomUUID()
    }
    const existing = window.localStorage.getItem(storageKey)
    if (existing) {
      return existing
    }
    const next = crypto.randomUUID()
    window.localStorage.setItem(storageKey, next)
    return next
  }, [])

  const createMutation = useMutation({
    mutationFn: async (payload: CreateStoryRequest) => {
      const story = await createStory(payload)
      await startWorkspaceRun(
        payload.storyId,
        payload.prompt,
        {
          storyId: payload.storyId,
          title: payload.title,
          premise: payload.premise,
          style: null,
          updatedAt: null,
          localOnly: false,
          nodes: [],
          activeNodeId: null,
          contentByNodeId: {},
          assistantThread: [],
          runBridge: {
            activeRunId: payload.runId,
            runAfterSeq: 0,
            runSyncStatus: 'running',
            runSyncUpdatedAt: null,
            lastCompletedChapter: null,
          },
        },
        {
          premise: payload.premise,
          outline: [],
          characters: payload.characters ?? [],
          worldRules: [],
          timeline: [],
          relationshipState: [],
          foreshadowLedger: [],
        },
        payload.wordCount,
      )
      return story
    },
    onSuccess: (data) => {
      navigate(`/stories/${data.storyId}/workspace`)
    },
  })

  return (
    <section className='creation-onboarding-page'>
      <div className='creation-onboarding'>
        <div className='creation-onboarding__logo'>✎</div>
        <h1>新建小说</h1>
        <p>先和 AI 打磨灵感，再填写作品资料并开始创作</p>
        <div className='creation-onboarding__columns'>
          <InspirationChatPanel sessionId={inspirationSessionId} />
          <div className='creation-onboarding__card panel'>
            <div className='creation-form-panel__header'>
              <div>
                <div className='workspace-sidebar__eyebrow'>作品资料</div>
                <h2>创建工作台</h2>
              </div>
            </div>
            <StoryCreateForm
              onSubmit={async (payload: CreateStoryRequest) => {
                await createMutation.mutateAsync(payload)
              }}
              isSubmitting={createMutation.isPending}
            />
            {createMutation.isError ? <div className='assistant-panel__error'>创建失败，请检查后端接口是否已启动。</div> : null}
          </div>
        </div>
      </div>
    </section>
  )
}
