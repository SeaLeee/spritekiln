import { BookOpen, Box, Flame, FolderKanban, House, Plug, Settings as Gear, Sparkles } from 'lucide-react'
import { NavLink, Outlet, createBrowserRouter, RouterProvider } from 'react-router-dom'
import { Logo } from './components/ui'
import Design from './pages/Design'
import Home from './pages/Home'
import Jobs from './pages/Jobs'
import Projects from './pages/Projects'
import Settings from './pages/Settings'
import Skills from './pages/Skills'
import Studio from './pages/Studio'
import ThreeD from './pages/ThreeD'

const NAV = [
  { to: '/', label: '主页', icon: House, end: true },
  { to: '/studio', label: '工作台', icon: Sparkles },
  { to: '/projects', label: '项目', icon: FolderKanban },
  { to: '/three', label: '3D 管线', icon: Box },
  { to: '/design', label: '策划', icon: BookOpen },
  { to: '/skills', label: 'Skill / API', icon: Plug },
  { to: '/jobs', label: '窑炉记录', icon: Flame },
]

function Shell() {
  return (
    <div className="h-full flex">
      <nav className="w-[68px] shrink-0 bg-ink text-white flex flex-col items-center py-3 gap-1" aria-label="主导航">
        <NavLink to="/" className="mb-3" aria-label="SpriteKiln 首页"><Logo compact /></NavLink>
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end} title={label}
            className={({ isActive }) => `w-14 rounded-lg py-2 flex flex-col items-center gap-0.5 text-[10px] ${isActive ? 'bg-white/12 text-white' : 'text-white/60 hover:text-white hover:bg-white/5'}`}>
            {({ isActive }) => (<>
              <Icon size={18} strokeWidth={1.8} className={isActive ? 'text-ember' : ''} />
              <span>{label}</span>
            </>)}
          </NavLink>
        ))}
        <NavLink to="/settings" title="设置" className={({ isActive }) => `mt-auto w-14 rounded-lg py-2 flex flex-col items-center gap-0.5 text-[10px] ${isActive ? 'bg-white/12' : 'text-white/60 hover:text-white'}`}>
          <Gear size={18} strokeWidth={1.8} /><span>设置</span>
        </NavLink>
      </nav>
      <div className="flex-1 min-w-0 h-full">
        <Outlet />
      </div>
    </div>
  )
}

const router = createBrowserRouter([
  {
    element: <Shell />,
    children: [
      { path: '/', element: <Home /> },
      { path: '/studio', element: <Studio /> },
      { path: '/studio/:pid', element: <Studio /> },
      { path: '/projects', element: <Projects /> },
      { path: '/three', element: <ThreeD /> },
      { path: '/design', element: <Design /> },
      { path: '/design/:pid', element: <Design /> },
      { path: '/skills', element: <Skills /> },
      { path: '/jobs', element: <Jobs /> },
      { path: '/settings', element: <Settings /> },
    ],
  },
])

export default function App() {
  return <RouterProvider router={router} />
}
