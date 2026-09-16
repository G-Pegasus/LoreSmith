import { useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { InspirationChatPanel } from '../features/stories/InspirationChatPanel'
import { StoryCreateForm } from '../features/stories/StoryCreateForm'
import { deleteInspirationSession } from '../lib/api/inspiration'
import { createStory } from '../lib/api/stories'
import { startWorkspaceRun } from '../lib/api/workspace'
import type { CreateStoryRequest, InspirationSettings } from '../lib/types/api'
import './pages.css'

const INSPIRATION_SESSION_STORAGE_KEY = 'ainovel:new-story-inspiration-session'

/** 会话 id 只在这里读写：新建页是公共入口，同一浏览器共用一条会话，「重置」就是把它轮换掉。 */
function readOrCreateInspirationSessionId() {
  if (typeof window === 'undefined') {
    return crypto.randomUUID()
  }
  const existing = window.localStorage.getItem(INSPIRATION_SESSION_STORAGE_KEY)
  if (existing) {
    return existing
  }
  const next = crypto.randomUUID()
  window.localStorage.setItem(INSPIRATION_SESSION_STORAGE_KEY, next)
  return next
}

export function NewStoryPage() {
  const navigate = useNavigate()
  // 每确认一次就换一个 seq：连续两次确认同内容时也要能触发表单覆盖。
  const [settingsFill, setSettingsFill] = useState<{ seq: number; settings: InspirationSettings } | null>(null)
  const settingsFillSeq = useRef(0)
  const [inspirationSessionId, setInspirationSessionId] = useState(readOrCreateInspirationSessionId)
  // 重置计数：右侧表单靠它重挂载回到初始值（不能靠喂空值 —— StoryCreateForm 对空值有守卫）
  const [formEpoch, setFormEpoch] = useState(0)

  /**
   * 完全重置：对话、设定单、右侧工作台一起清空。
   *
   * 顺序很关键 —— 必须先把新 id 写进本地存储，再拿旧 id 去发删库请求，否则旧 id 就丢了。
   * 界面上的「重置感」完全由换 id 触发的重挂载提供，立即生效；删库只是顺手清理，
   * 所以 fire-and-forget：后端没起来时，重置按钮也该照常好用。
   */
  const resetInspiration = () => {
    const staleSessionId = inspirationSessionId
    const nextSessionId = crypto.randomUUID()
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(INSPIRATION_SESSION_STORAGE_KEY, nextSessionId)
    }
    setInspirationSessionId(nextSessionId)
    // 不清这个，重挂载后的表单会立刻把上次确认的设定回填回来，重置当场失效
    setSettingsFill(null)
    setFormEpoch((current) => current + 1)
    void deleteInspirationSession(staleSessionId).catch(() => {
      // 旧会话没删掉只会让库里多一行，不影响本次重置
    })
  }

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
          <InspirationChatPanel
            key={inspirationSessionId}
            sessionId={inspirationSessionId}
            onConfirmed={(settings) => {
              settingsFillSeq.current += 1
              setSettingsFill({ seq: settingsFillSeq.current, settings })
            }}
            onReset={resetInspiration}
          />
          <div className='creation-onboarding__card panel'>
            <div className='creation-form-panel__header'>
              <div>
                <div className='workspace-sidebar__eyebrow'>作品资料</div>
                <h2>创建工作台</h2>
              </div>
            </div>
            <StoryCreateForm
              key={formEpoch}
              fill={settingsFill}
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
