"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Header,
  HeaderContainer,
  HeaderGlobalAction,
  HeaderGlobalBar,
  HeaderMenuButton,
  HeaderName,
  SideNav,
  SideNavItems,
  SideNavLink,
  SkipToContent,
  Content,
  Theme,
  Tag,
} from "@carbon/react";
import {
  Dashboard,
  FlowData,
  Wallet,
  Notification,
  UserAvatar,
} from "@carbon/icons-react";
import type { ReactNode } from "react";
import { useSanjeevani } from "@/lib/store";

const NAV_ITEMS = [
  { href: "/", label: "War Room", icon: Dashboard },
  { href: "/waterfall", label: "Live Pipeline", icon: FlowData },
  { href: "/settlement", label: "Settlement", icon: Wallet },
];

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { pendingApprovalsCount } = useSanjeevani();

  return (
    <Theme theme="g100">
      <HeaderContainer
        render={({ isSideNavExpanded, onClickSideNavExpand }: { isSideNavExpanded: boolean; onClickSideNavExpand: () => void }) => (
          <>
            <Header aria-label="Sanjeevani">
              <SkipToContent />
              <HeaderMenuButton
                aria-label="Open menu"
                onClick={onClickSideNavExpand}
                isActive={isSideNavExpanded}
                isCollapsible
              />
              <HeaderName as={Link} href="/" prefix="SANJEEVANI">
                Supply Chain Command
              </HeaderName>
              <HeaderGlobalBar>
                <HeaderGlobalAction aria-label="Notifications" tooltipAlignment="end">
                  <span className="sanjeevani-header-notif-wrap">
                    <Notification size={20} />
                    {pendingApprovalsCount > 0 && (
                      <Tag type="red" size="sm" className="sanjeevani-header-notif-tag">
                        {pendingApprovalsCount}
                      </Tag>
                    )}
                  </span>
                </HeaderGlobalAction>
                <HeaderGlobalAction aria-label="Rajesh Kumar" tooltipAlignment="end">
                  <UserAvatar size={20} />
                </HeaderGlobalAction>
              </HeaderGlobalBar>
              <SideNav
                aria-label="Side navigation"
                expanded={isSideNavExpanded}
                isPersistent={false}
                onSideNavBlur={onClickSideNavExpand}
              >
                <SideNavItems>
                  {NAV_ITEMS.map((item) => (
                    <SideNavLink
                      key={item.href}
                      as={Link}
                      href={item.href}
                      renderIcon={item.icon}
                      isActive={pathname === item.href}
                    >
                      {item.label}
                    </SideNavLink>
                  ))}
                </SideNavItems>
              </SideNav>
            </Header>
            <Content className="sanjeevani-shell-content">{children}</Content>
          </>
        )}
      />
    </Theme>
  );
}
