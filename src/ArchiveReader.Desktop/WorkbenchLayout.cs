using System.IO;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using Microsoft.Win32;

namespace ArchiveReader;

public partial class WorkbenchWindow
{
    string? layoutProposal;
    HashSet<string> layoutIssueIds=[];
    int? bookQualityNext;
    List<RegionItem> draftRegions=[];
    JsonObject? regionRecognition;
    string KrakenExecutable=>System.IO.Path.Combine(System.IO.Path.GetDirectoryName(PythonRuntime.Resolve()) ?? "","kraken.exe");
    void LayoutTabChanged(object sender,SelectionChangedEventArgs e) { if(e.Source==Tabs && Surface!=null && PageImage?.Source!=null) DrawOverlays(); }
    void ToggleLayoutNumbers(object sender,RoutedEventArgs e)=>DrawOverlays();
    void ChooseLayoutModel(object sender,RoutedEventArgs e)
    { var dialog=new OpenFileDialog { Filter="Kraken|*.mlmodel;*.safetensors" }; if(dialog.ShowDialog()==true) LayoutSegmentation.Text=dialog.FileName; }
    async void ProposeWholeLayout(object sender,RoutedEventArgs e)=>await ProposeLayout(false);
    async void ProposeRegionLayout(object sender,RoutedEventArgs e)=>await ProposeLayout(true);
    async Task ProposeLayout(bool scoped)=>await Run(async()=>
    {
        if(scoped && selectedRegion==null) throw new Exception(T("Виберіть збережений запис або колонку."));
        Status.Text=T("Пошук рядків і пропозиція структури…");
        var result=await Call("layout_propose",new() { ["id"]=page.Id,["annotation"]=scoped?selectedRegion:null,["mode"]=SelectedTag(LayoutMode),["reuse"]=ReuseLines.IsChecked==true,["executable"]=KrakenExecutable,["segmentation"]=LayoutSegmentation.Text });
        SetLayoutProposal(result);
        Status.Text=F("Пропозицій: {0}. Перевірте межі та порядок перед збереженням.",draftRegions.Count);
    });
    void SetLayoutProposal(JsonNode result)
    {
        layoutProposal=result["id"]!.ToString(); draftRegions=result["regions"]!.AsArray().Select(n=>new RegionItem(n!.AsObject())).ToList();
        LayoutDrafts.ItemsSource=draftRegions; LayoutDrafts.SelectAll(); DrawOverlays();
    }
    async Task InitializeLayoutSmoke()=>SetLayoutProposal(await Call("layout_propose",new() { ["id"]=page.Id,["mode"]="columns",["reuse"]=true,["executable"]=KrakenExecutable }));
    void SelectLayoutDraft(object sender,SelectionChangedEventArgs e)
    {
        if(LayoutDrafts.SelectedItem is not RegionItem item) return;
        NewRegion(sender,new RoutedEventArgs());
        SetSelectedTag(RegionKind,item.Data["kind"]!.ToString()); RegionLabel.Text=item.Data["label"]?.ToString() ?? "";
        ReadingPosition.Text=item.Data["reading_order"]?.ToString() ?? "";
        var b=item.Data["rect"]!.AsArray(); rectangle=new Rect(b[0]!.GetValue<double>(),b[1]!.GetValue<double>(),b[2]!.GetValue<double>(),b[3]!.GetValue<double>()); DrawOverlays();
    }
    void SelectAllDrafts(object sender,RoutedEventArgs e)=>LayoutDrafts.SelectAll();
    async void ApplyLayout(object sender,RoutedEventArgs e)=>await Run(async()=>
    {
        if(layoutProposal==null) return;
        var selected=new JsonArray(); foreach(RegionItem row in LayoutDrafts.SelectedItems) selected.Add(row.Id);
        var result=await Call("layout_apply",new() { ["id"]=page.Id,["proposal"]=layoutProposal,["regions"]=selected });
        layoutProposal=null; draftRegions=[]; LayoutDrafts.ItemsSource=null; rectangle=null;
        await RefreshRegions(); Status.Text=F("Збережено ділянок: {0}. Межі можна виправити мишею у вкладці розмітки.",result["added"]);
    });
    void SelectOrderedRegion(object sender,SelectionChangedEventArgs e)
    { if(ReadingOrderRows.SelectedItem is RegionItem row) Regions.SelectedItem=regions.FirstOrDefault(r=>r.Id==row.Id); }
    async void MoveReadingOrder(object sender,RoutedEventArgs e)=>await Run(async()=>
    {
        int index=ReadingOrderRows.SelectedIndex; int target=index+int.Parse(((Button)sender).Tag.ToString()!);
        if(index<0 || target<0 || target>=ReadingOrderRows.Items.Count) return;
        var items=ReadingOrderRows.Items.Cast<RegionItem>().ToList(); (items[index],items[target])=(items[target],items[index]);
        var ids=new JsonArray(); foreach(var row in items) ids.Add(row.Id);
        await Call("layout_order",new() { ["id"]=page.Id,["regions"]=ids });
        await RefreshRegions(items[target].Id); ReadingOrderRows.SelectedIndex=target; Status.Text=T("Порядок читання збережено.");
    });
    async void RecognizeSavedRegion(object sender,RoutedEventArgs e)=>await Run(async()=>
    {
        if(selectedRegion==null) throw new Exception(T("Виберіть збережений запис або колонку."));
        if(SelectedTag(EngineA)!="kraken") throw new Exception(T("Розпізнавання записів і колонок зараз підтримує Kraken."));
        Status.Text=T("Розпізнавання окремої ділянки…");
        regionRecognition=(await Call("recognize_region",new() { ["id"]=page.Id,["annotation"]=selectedRegion,["model"]=ModelA.Text,["executable"]=KrakenExecutable,["segmentation"]=LayoutSegmentation.Text,["mode"]=SelectedTag(LayoutMode),["force"]=ForceRegionRecognition.IsChecked==true,["use_saved_lines"]=UseSavedRecognitionLines.IsChecked==true })).AsObject();
        RegionOcrResult.Text=regionRecognition["text"]!.ToString(); Status.Text=regionRecognition["review_flags"] is JsonArray flags&&flags.Count>0?T("Мало читабельних рядків. Перевірте межі та поділ; результат не підтверджено."):T(regionRecognition["reused"]?.GetValue<bool>()==true?"Використано збережене прочитання незмінної ділянки.":"Ділянку розпізнано. Повний OCR сторінки та ручні виправлення збережено.");
    });
    async void ApplyRegionOcr(object sender,RoutedEventArgs e)=>await Run(async()=>
    {
        if(regionRecognition?["id"]==null) return;
        var result=await Call("region_recognition_apply",new() { ["id"]=page.Id,["run"]=regionRecognition["id"]!.ToString() });
        await RefreshRegions(); Status.Text=F("Додано неперевірених рядків: {0}.",result["added"]); if(result["conflicts"] is JsonArray conflicts&&conflicts.Count>0)Status.Text+=" · "+T("Наявні рядки залишено без перезапису")+": "+conflicts.Count;
    });
    void UseRegionOcrText(object sender,RoutedEventArgs e)
    {
        if(regionRecognition==null || selectedRegion==null) return;
        // Only copy into the editor for the actual recognized source region.
        var region=regions.FirstOrDefault(r=>r.Id==selectedRegion);
        if(region==null || selectedRegion!=regionRecognition["annotation"]!.ToString() || region.Data["rect"]!.ToJsonString()!=regionRecognition["rect"]!.ToJsonString()) { Status.Text=T("Результат змінився. Оновіть список."); return; }
        RegionText.Text=RegionOcrResult.Text; RegionVerified.IsChecked=false; Tabs.SelectedIndex=0;
        Status.Text=T("Текст перенесено для редагування. Перевірте його й збережіть ділянку.");
    }
    async void AssembleRegionText(object sender,RoutedEventArgs e)=>await Run(async()=>
    {
        regionRecognition=(await Call("region_ordered_text",new() { ["id"]=page.Id,["annotation"]=selectedRegion })).AsObject();
        RegionOcrResult.Text=regionRecognition["text"]!.ToString(); Status.Text=regionRecognition["review_flags"] is JsonArray flags&&flags.Count>0?T("Мало читабельних рядків. Перевірте межі та поділ; результат не підтверджено."):T("Текст зібрано зі збережених рядків. Перевірте порядок і повноту.");
    });

    void ChooseSecondLayoutModel(object sender,RoutedEventArgs e)
    {var dialog=new OpenFileDialog{Filter="Kraken|*.mlmodel;*.safetensors"};if(dialog.ShowDialog()==true)LayoutSegmentationB.Text=dialog.FileName;}
    async void CheckLayoutQuality(object sender,RoutedEventArgs e)=>await Run(async()=>await ReadLayoutQuality());
    async Task ReadLayoutQuality()
    {
        var result=await Call("layout_quality",new(){["id"]=page.Id});layoutIssueIds=[];
        var labels=new Dictionary<string,string>{{"tiny",T("Підозріло мала ділянка")},{"overlap",T("Перекриття рядків")},{"possible_gap",T("Можливий проміжок між рядками")}};
        LayoutQualityText.Text=string.Join("\n",result["issues"]!.AsArray().Select(n=>{foreach(var id in n!["annotations"]!.AsArray())layoutIssueIds.Add(id!.ToString());return labels.GetValueOrDefault(n["kind"]!.ToString(),n["kind"]!.ToString())+": "+string.Join(", ",n["annotations"]!.AsArray().Select(id=>regions.FirstOrDefault(r=>r.Id==id!.ToString())?.Label??id!.ToString()));}));
        if(LayoutQualityText.Text.Length==0)LayoutQualityText.Text=T("Геометричних попереджень немає; повноту тексту не підтверджено.");if(result["truncated"]?.GetValue<bool>()==true)LayoutQualityText.Text+="\n"+T("Перевірку обмежено; частина рядків потребує окремого перегляду.");DrawOverlays();
    }
    async void MergeSelectedLines(object sender,RoutedEventArgs e)=>await EditLines("merge");
    async void SplitSelectedLine(object sender,RoutedEventArgs e)=>await EditLines("split");
    async Task EditLines(string operation)=>await Run(async()=>
    {
        var ids=new JsonArray();foreach(RegionItem row in ReadingOrderRows.SelectedItems)ids.Add(row.Id);
        var quality=await Call("layout_quality",new(){["id"]=page.Id});var result=await Call("layout_edit_lines",new(){["id"]=page.Id,["regions"]=ids,["expected"]=quality["snapshot"]!.ToString(),["operation"]=operation});
        await RefreshRegions(result["ids"]![0]!.ToString());await ReadLayoutQuality();
    });
    async void LoadBookQuality(object sender,RoutedEventArgs e)=>await Run(async()=>await ReadBookQuality(0));
    async void NextBookQuality(object sender,RoutedEventArgs e)=>await Run(async()=>{if(bookQualityNext is int next)await ReadBookQuality(next);});
    async Task ReadBookQuality(int offset)
    {
        var result=await Call("book_quality_map",new(){["id"]=page.Id,["offset"]=offset});bookQualityNext=result["next_offset"]?.GetValue<int>();
        var labels=new Dictionary<string,string>{{"page_processing",T("Завдання сторінки не завершено")},{"recognition_failed",T("Збій читання ділянки")},{"empty_result",T("Порожній результат")},{"missing_page",T("Позначений пропущений аркуш")},{"unprocessed",T("Немає прочитаного тексту")},{"machine_read",T("Прочитано; не перевірено")},{"partly_verified",T("Частину рядків перевірено")},{"saved_lines_verified",T("Збережені рядки перевірено; повнота невідома")},{"layout_review",T("Потрібна перевірка меж")}};
        BookQualityText.Text=string.Join("\n",result["pages"]!.AsArray().Select(n=>n!["number"]+": "+labels[n["state"]!.ToString()]+" · "+n["verified_lines"]+"/"+n["line_count"]))+"\n"+T("Перевірені рядки не гарантують повного охоплення сторінки.");
    }
    async void CompareLayoutModels(object sender,RoutedEventArgs e)=>await Run(async()=>
    {
        if(string.IsNullOrWhiteSpace(LayoutSegmentationB.Text))throw new Exception(T("Виберіть другу модель сегментації."));
        var result=await Call("layout_compare",new(){["id"]=page.Id,["annotation"]=selectedRegion,["mode"]=SelectedTag(LayoutMode),["executable"]=KrakenExecutable,["models"]=new JsonArray(new JsonObject{["name"]="A",["path"]=LayoutSegmentation.Text},new JsonObject{["name"]="B",["path"]=LayoutSegmentationB.Text})});
        LayoutComparisons.ItemsSource=result["models"]!.AsArray().Select(n=>new GenealogyRow(n!.AsObject(),n["name"]+": "+(n["error"]?.ToString()??n["proposal"]!["regions"]!.AsArray().Count.ToString()))).ToList();LayoutComparisons.SelectedIndex=0;
    });
    void SelectLayoutComparison(object sender,SelectionChangedEventArgs e)
    {if(LayoutComparisons.SelectedItem is GenealogyRow row&&row.Data["proposal"] is JsonNode proposal)SetLayoutProposal(proposal);}
    async void RecognizeVariants(object sender,RoutedEventArgs e)=>await Run(async()=>
    {
        if(selectedRegion==null)throw new Exception(T("Виберіть збережений запис або колонку."));
        if(SelectedTag(EngineA)!="kraken")throw new Exception(T("Розпізнавання записів і колонок зараз підтримує Kraken."));
        var rows=new List<GenealogyRow>();RegionVariants.ItemsSource=rows;
        foreach(var variant in new[]{"original","upscale2","contrast"})
        {
            try{var result=await Call("recognize_region",new(){["id"]=page.Id,["annotation"]=selectedRegion,["model"]=ModelA.Text,["executable"]=KrakenExecutable,["segmentation"]=LayoutSegmentation.Text,["mode"]=SelectedTag(LayoutMode),["variant"]=variant,["use_saved_lines"]=UseSavedRecognitionLines.IsChecked==true});rows.Add(new GenealogyRow(result.AsObject(),T(variant=="original"?"Оригінал":variant=="upscale2"?"Збільшення ×2":"Корекція контрасту")));}
            catch(OperationCanceledException){throw;}
            catch(Exception ex){rows.Add(new GenealogyRow(new JsonObject{["error"]=ex.Message},variant+": "+ex.Message));}
            RegionVariants.ItemsSource=rows.ToList();
        }
        RegionVariants.SelectedIndex=0;
    });
    void SelectRecognitionVariant(object sender,SelectionChangedEventArgs e)
    {if(RegionVariants.SelectedItem is GenealogyRow row){regionRecognition=row.Data["error"]==null?row.Data:null;RegionOcrResult.Text=row.Data["text"]?.ToString()??row.Data["error"]?.ToString()??"";var preview=regionRecognition?["path"] is JsonNode folder?Path.Combine(folder.ToString(),"input.png"):"";VariantPreview.Source=File.Exists(preview)?Bitmap(preview):null;}}

    JsonObject? pageReview;
    void SetPageReview(JsonNode result)
    {
        pageReview=result.AsObject();PageReviewText.Text=result["text"]?.ToString()??"";
        PageReviewSummary.Text=result["counts"] is JsonObject counts?string.Join(" · ",counts.Select(pair=>T(pair.Key switch{"pending"=>"Очікують","running"=>"Виконуються","done"=>"Ділянок із текстом","empty"=>"Порожній результат",_=>"Помилки"})+": "+pair.Value))+(result["stale"]?.GetValue<bool>()==true?" · "+T("План застарів; створіть новий."):""):T("Завдань для сторінки немає.");if(result["interrupted_units"]?.GetValue<int>()>0)PageReviewSummary.Text+=" · "+T("Попередній процес перервано; можна продовжити.");DrawOverlays();
    }
    async void StartPageReview(object sender,RoutedEventArgs e)=>await Run(async()=>
    {
        if(SelectedTag(EngineA)!="kraken")throw new Exception(T("Розпізнавання записів і колонок зараз підтримує Kraken."));
        SetPageReview(await Call("page_review_start",new(){["id"]=page.Id,["model"]=ModelA.Text,["segmentation"]=LayoutSegmentation.Text,["executable"]=KrakenExecutable,["mode"]=SelectedTag(PageReadingMode),["spread"]=PageSpread.IsChecked==true,["use_saved"]=PageUseSaved.IsChecked==true}));await RefreshRegions();
    });
    async void LoadPageReview(object sender,RoutedEventArgs e)=>await Run(async()=>SetPageReview(await Call("page_review_status",new(){["id"]=page.Id})));
    async void ContinuePageReview(object sender,RoutedEventArgs e)=>await ProcessPageReview(false);
    async void RetryPageFailures(object sender,RoutedEventArgs e)=>await ProcessPageReview(true);
    async Task ProcessPageReview(bool retry)=>await Run(async()=>
    {
        if(pageReview?["job"]==null)SetPageReview(await Call("page_review_status",new(){["id"]=page.Id}));
        if(pageReview?["job"]==null)throw new Exception(T("Спочатку створіть план сторінки."));
        bool first=true;
        while(true)
        {
            work!.Token.ThrowIfCancellationRequested();var result=await Call("page_review_step",new(){["job"]=pageReview["job"]!.ToString(),["retry_failed"]=first&&retry});first=false;SetPageReview(result);
            if(result["counts"]!["pending"]!.GetValue<int>()==0)break;
        }
    });
    void OpenPageReviewReport(object sender,RoutedEventArgs e)
    {if(pageReview?["report"] is JsonNode report&&File.Exists(report.ToString()))System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(report.ToString()){UseShellExecute=true});}
    void OpenPageCorpus(object sender,RoutedEventArgs e)=>new CorpusWindow(page.Id,ModelA.Text,worker){Owner=this}.ShowDialog();
}
