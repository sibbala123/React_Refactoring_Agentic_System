import { Text } from '@rocket.chat/fuselage';
import React from 'react';

import { useTranslation } from '../../providers/TranslationProvider';
import { DescriptionList } from './DescriptionList';
import { formatMemorySize } from './formatters';

function DescriptionEntry({ label, value }) {
	return <DescriptionList.Entry label={label}>{value}</DescriptionList.Entry>;
}

export function UsageSection({ statistics, isLoading }) {
	const s = (fn) => (isLoading ? <Text.Skeleton animated width={'1/2'} /> : fn());
	const t = useTranslation();

	return <>
		<h3>{t('Usage')}</h3>
		<DescriptionList>
			<DescriptionEntry label={t('Stats_Total_Users')} value={s(() => statistics.totalUsers)} />
			<DescriptionEntry label={t('Stats_Active_Users')} value={s(() => statistics.activeUsers)} />
			<DescriptionEntry label={t('Stats_Non_Active_Users')} value={s(() => statistics.nonActiveUsers)} />
			<DescriptionEntry label={t('Stats_Total_Connected_Users')} value={s(() => statistics.totalConnectedUsers)} />
			<DescriptionEntry label={t('Stats_Online_Users')} value={s(() => statistics.onlineUsers)} />
			<DescriptionEntry label={t('Stats_Away_Users')} value={s(() => statistics.awayUsers)} />
			<DescriptionEntry label={t('Stats_Offline_Users')} value={s(() => statistics.offlineUsers)} />
			<DescriptionEntry label={t('Stats_Total_Rooms')} value={s(() => statistics.totalRooms)} />
			<DescriptionEntry label={t('Stats_Total_Channels')} value={s(() => statistics.totalChannels)} />
			<DescriptionEntry label={t('Stats_Total_Private_Groups')} value={s(() => statistics.totalPrivateGroups)} />
			<DescriptionEntry label={t('Stats_Total_Direct_Messages')} value={s(() => statistics.totalDirect)} />
			<DescriptionEntry label={t('Stats_Total_Livechat_Rooms')} value={s(() => statistics.totalLivechat)} />
			<DescriptionEntry label={t('Total_Discussions')} value={s(() => statistics.totalDiscussions)} />
			<DescriptionEntry label={t('Total_Threads')} value={s(() => statistics.totalThreads)} />
			<DescriptionEntry label={t('Stats_Total_Messages')} value={s(() => statistics.totalMessages)} />
			<DescriptionEntry label={t('Stats_Total_Messages_Channel')} value={s(() => statistics.totalChannelMessages)} />
			<DescriptionEntry label={t('Stats_Total_Messages_PrivateGroup')} value={s(() => statistics.totalPrivateGroupMessages)} />
			<DescriptionEntry label={t('Stats_Total_Messages_Direct')} value={s(() => statistics.totalDirectMessages)} />
			<DescriptionEntry label={t('Stats_Total_Messages_Livechat')} value={s(() => statistics.totalLivechatMessages)} />
			<DescriptionEntry label={t('Stats_Total_Uploads')} value={s(() => statistics.uploadsTotal)} />
			<DescriptionEntry label={t('Stats_Total_Uploads_Size')} value={s(() => formatMemorySize(statistics.uploadsTotalSize))} />
			{statistics && statistics.apps && <>
				<DescriptionEntry label={t('Stats_Total_Installed_Apps')} value={statistics.apps.totalInstalled} />
				<DescriptionEntry label={t('Stats_Total_Active_Apps')} value={statistics.apps.totalActive} />
			</>}
			<DescriptionEntry label={t('Stats_Total_Integrations')} value={s(() => statistics.integrations.totalIntegrations)} />
			<DescriptionEntry label={t('Stats_Total_Incoming_Integrations')} value={s(() => statistics.integrations.totalIncoming)} />
			<DescriptionEntry label={t('Stats_Total_Active_Incoming_Integrations')} value={s(() => statistics.integrations.totalIncomingActive)} />
			<DescriptionEntry label={t('Stats_Total_Outgoing_Integrations')} value={s(() => statistics.integrations.totalOutgoing)} />
			<DescriptionEntry label={t('Stats_Total_Active_Outgoing_Integrations')} value={s(() => statistics.integrations.totalOutgoingActive)} />
			<DescriptionEntry label={t('Stats_Total_Integrations_With_Script_Enabled')} value={s(() => statistics.integrations.totalWithScriptEnabled)} />
		</DescriptionList>
	</>;
}