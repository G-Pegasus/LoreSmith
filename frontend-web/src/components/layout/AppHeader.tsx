import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'
import { fetchStories } from '../../lib/api/stories'

const navItems = [
  {
    to: '/',
    label: '探索',
    isActive: (pathname: string) => pathname === '/',
  },
  {
    to: '/stories',
    label: '我的作品',
    isActive: (pathname: string) => pathname === '/stories',
  },
  {
    to: '/stories/new',
    label: '新建作品',
    isActive: (pathname: string) => pathname === '/stories/new',
  },
  {
    to: '/stories/new',
    label: '共享工作台',
    isActive: (pathname: string) => /^\/stories\/[^/]+\/(workspace|reference)$/.test(pathname),
  },
]

export function AppHeader() {
  const navigate = useNavigate()
  const location = useLocation()
  const storiesQuery = useQuery({ queryKey: ['stories'], queryFn: fetchStories })

  const workspaceEntry = useMemo(() => {
    const stories = storiesQuery.data ?? []
    const latestStory = [...stories].sort((a, b) => {
      const aTime = a.createdAt ? new Date(a.createdAt).getTime() : 0
      const bTime = b.createdAt ? new Date(b.createdAt).getTime() : 0
      return bTime - aTime
    })[0]

    return latestStory ? `/stories/${latestStory.storyId}/workspace` : '/stories/new'
  }, [storiesQuery.data])

  return (
    <header className='app-header'>
      <button className='brand' onClick={() => navigate('/')}>
        <span className='brand__logo'>✎</span>
        <span className='brand__text'>墨韵<span className='brand__text-accent'>AI</span></span>
      </button>

      <nav className='app-header__nav'>
        {navItems.map((item) => (
          <button
            key={item.label}
            type='button'
            className={`app-header__link ${item.isActive(location.pathname) ? 'is-active' : ''}`}
            onClick={() => navigate(item.label === '共享工作台' ? workspaceEntry : item.to)}
          >
            {item.label}
          </button>
        ))}
      </nav>

    </header>
  )
}
