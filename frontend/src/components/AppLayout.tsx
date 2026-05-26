import { Layout, Menu, Typography } from 'antd'
import {
  DashboardOutlined,
  LineChartOutlined,
} from '@ant-design/icons'
import { Link, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'

const { Header, Sider, Content } = Layout

const menuItems = [
  { key: '/', icon: <DashboardOutlined />, label: <Link to="/">Dashboard</Link> },
  { key: '/benchmarks', icon: <LineChartOutlined />, label: <Link to="/benchmarks">Benchmarks</Link> },
]

export default function AppLayout({ children }: { children: ReactNode }) {
  const location = useLocation()
  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider theme="dark" breakpoint="lg" collapsedWidth="0">
        <div style={{ padding: 16, textAlign: 'center' }}>
          <Typography.Title level={5} style={{ color: '#fff', margin: 0 }}>
            Light Server
          </Typography.Title>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
        />
      </Sider>
      <Layout>
        <Header style={{ background: '#fff', padding: '0 24px' }}>
          <Typography.Title level={4} style={{ margin: '16px 0' }}>
            Light Server
          </Typography.Title>
        </Header>
        <Content style={{ margin: 24, padding: 24, background: '#fff' }}>
          {children}
        </Content>
      </Layout>
    </Layout>
  )
}
