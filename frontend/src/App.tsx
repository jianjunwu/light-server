import { Suspense } from 'react'
import { useRoutes } from 'react-router-dom'
import { Spin } from 'antd'
import AppLayout from '@/components/AppLayout'
import routes from './routes'

function App() {
  const element = useRoutes(routes)
  return (
    <AppLayout>
      <Suspense fallback={<Spin style={{ display: 'block', margin: '100px auto' }} />}>
        {element}
      </Suspense>
    </AppLayout>
  )
}

export default App
