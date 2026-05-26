import { lazy } from 'react'
import type { RouteObject } from 'react-router-dom'

const Dashboard = lazy(() => import('@/pages/Dashboard'))
const ModelDetail = lazy(() => import('@/pages/ModelDetail'))
const Repository = lazy(() => import('@/pages/Repository'))
const BenchmarkList = lazy(() => import('@/pages/Benchmarks/List'))
const BenchmarkCreate = lazy(() => import('@/pages/Benchmarks/Create'))
const BenchmarkDetail = lazy(() => import('@/pages/Benchmarks/Detail'))
const ConfigPage = lazy(() => import('@/pages/Config'))

const routes: RouteObject[] = [
  { path: '/', element: <Dashboard /> },
  { path: '/models/:name', element: <ModelDetail /> },
  { path: '/repository', element: <Repository /> },
  { path: '/benchmarks', element: <BenchmarkList /> },
  { path: '/benchmarks/new', element: <BenchmarkCreate /> },
  { path: '/benchmarks/:id', element: <BenchmarkDetail /> },
  { path: '/config', element: <ConfigPage /> },
]

export default routes
