import difflib

def cluster_feedback(feedback_list, threshold=0.7):
    """
    将反馈列表聚类成相似反馈组，返回去重后的需求列表。
    使用 difflib 计算文本相似度，阈值可调。
    """
    if not feedback_list:
        return []
    clusters = []
    for feedback in feedback_list:
        added = False
        for cluster in clusters:
            representative = cluster[0]  # 使用聚类中第一个反馈作为代表
            similarity = difflib.SequenceMatcher(None, feedback, representative).ratio()
            if similarity >= threshold:
                cluster.append(feedback)
                added = True
                break
        if not added:
            clusters.append([feedback])
    # 将每个聚类转换为一个需求：使用第一个反馈作为代表
    requirements = [cluster[0] for cluster in clusters]
    return requirements
